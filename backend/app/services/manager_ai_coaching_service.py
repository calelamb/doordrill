from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session, selectinload

from app.core.config import get_settings
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.training import AdaptiveRecommendationOutcome, OverrideLabel
from app.models.user import User
from app.models.warehouse import FactRepDaily
from app.schemas.ai_meta import AiAttemptMeta, AiMeta
from app.schemas.manager_ai import (
    ManagerChatAnswerContent,
    ManagerChatClassification,
    OneOnOnePrepContent,
    OneOnOnePrepResponse,
    RepInsightContent,
    RepInsightResponse,
    SessionAnnotation,
    SessionAnnotationsResponse,
    TeamCoachingSummaryContent,
    TeamCoachingSummaryResponse,
    WeeklyTeamBriefingContent,
    WeeklyTeamBriefingResponse,
)
from app.schemas.knowledge import RetrievedChunk
from app.services.adaptive_training_service import AdaptiveTrainingService
from app.services.document_retrieval_service import DocumentRetrievalService
from app.services.management_cache_service import ManagementCacheService
from app.services.predictive_modeling_service import PredictiveModelingService
from app.services.prompt_version_resolver import prompt_version_resolver
from app.services.provider_clients import JsonLlmResult, JsonLlmRouter, JsonLlmRouterError

READINESS_THRESHOLD = 7.0
DEFAULT_COACHING_SYSTEM_PREFIX = (
    "You are a seasoned door-to-door sales manager preparing coaching feedback for your team. "
    "Be direct, evidence-based, and rep-focused."
)

RUBRIC_CATEGORY_KEYS = {
    "opening": "opening",
    "pitch": "pitch",
    "pitch_delivery": "pitch",
    "objection_handling": "objection_handling",
    "closing": "closing",
    "closing_technique": "closing",
    "professionalism": "professionalism",
}


class AiCoachingUnavailableError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "ai_provider_unavailable",
        attempts: list[AiAttemptMeta] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.attempts = list(attempts or [])

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "attempts": [attempt.model_dump(mode="json") for attempt in self.attempts],
        }


class AiCoachingDataUnavailableError(ValueError):
    def __init__(self, message: str, *, code: str = "ai_no_data") -> None:
        super().__init__(message)
        self.code = code

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
        }


def _score_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("score")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


def _linear_regression_slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    midpoint = (len(values) - 1) / 2
    average = sum(values) / len(values)
    numerator = sum((index - midpoint) * (value - average) for index, value in enumerate(values))
    denominator = sum((index - midpoint) ** 2 for index in range(len(values)))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[^.!?]+[.!?]", text.strip()))


def _trim_to_three_sentences(text: str) -> str:
    sentences = re.findall(r"[^.!?]+[.!?]", text.strip())
    if len(sentences) >= 3:
        return " ".join(sentence.strip() for sentence in sentences[:3]).strip()
    return text.strip()


class ManagerAiCoachingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.json_router = JsonLlmRouter(self.settings)
        self.adaptive_training_service = AdaptiveTrainingService()
        self.predictive_modeling_service = PredictiveModelingService()
        self.document_retrieval_service = DocumentRetrievalService(settings=self.settings)
        cache_size = max(128, self.settings.management_analytics_cache_max_entries)
        self.rep_insight_cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=3600,
            max_entries=cache_size,
        )
        self.one_on_one_prep_cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=2 * 3600,
            max_entries=cache_size,
        )
        self.weekly_team_briefing_cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=6 * 3600,
            max_entries=cache_size,
        )
        self.company_training_context_cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=30 * 60,
            max_entries=cache_size,
        )
        self.session_annotations_cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=4 * 3600,
            max_entries=cache_size,
        )

    def _get_coaching_system_prefix(self, db: Session, org_id: str | None = None) -> str:
        row = prompt_version_resolver.resolve(
            prompt_type="coaching",
            org_id=org_id,
            session_id=f"_coaching_{org_id or 'global'}_{id(db)}",
            db=db,
        )
        if row is not None and row.content:
            return row.content.strip()
        return DEFAULT_COACHING_SYSTEM_PREFIX

    def _manager_ai_cache_signature(self) -> dict[str, Any]:
        primary_provider = (self.settings.llm_provider or "").strip().lower()
        fallback_provider = self.json_router._resolve_fallback_provider(primary_provider)
        primary_model = self.json_router._resolve_model(primary_provider or "mock", fast=False, is_fallback=False)
        primary_fast_model = self.json_router._resolve_model(primary_provider or "mock", fast=True, is_fallback=False)
        fallback_model = (
            self.json_router._resolve_model(fallback_provider, fast=False, is_fallback=True)
            if fallback_provider
            else None
        )
        fallback_fast_model = (
            self.json_router._resolve_model(fallback_provider, fast=True, is_fallback=True)
            if fallback_provider
            else None
        )
        return {
            "primary_provider": primary_provider,
            "primary_model": primary_model,
            "primary_fast_model": primary_fast_model,
            "fallback_provider": fallback_provider,
            "fallback_model": fallback_model,
            "fallback_fast_model": fallback_fast_model,
        }

    def _call_manager_ai_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        task: str,
        fast: bool = False,
        validator: Any | None = None,
    ) -> JsonLlmResult:
        legacy_override = self.__dict__.get("_call_claude_json")
        if callable(legacy_override):
            try:
                payload = legacy_override(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                )
                validated = validator(payload) if validator else payload
                return JsonLlmResult(
                    payload=validated,
                    provider="legacy_override",
                    model="legacy_override",
                    real_call=False,
                    latency_ms=0,
                    fallback_used=False,
                    attempts=[],
                    status="live",
                )
            except AiCoachingUnavailableError:
                raise
            except Exception as exc:
                raise AiCoachingUnavailableError(
                    "Legacy manager AI override failed.",
                    code="ai_invalid_response",
                ) from exc
        try:
            return self.json_router.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                fast=fast,
                task=task,
                validator=validator,
            )
        except JsonLlmRouterError as exc:
            attempts = [
                AiAttemptMeta(
                    provider=attempt.provider,
                    model=attempt.model,
                    outcome=attempt.outcome,
                    latency_ms=attempt.latency_ms,
                    real_call=attempt.real_call,
                    task=attempt.task,
                    error=attempt.error,
                )
                for attempt in exc.attempts
            ]
            raise AiCoachingUnavailableError(str(exc), code=exc.code, attempts=attempts) from exc

    def _ai_meta_from_result(
        self,
        result: JsonLlmResult,
        *,
        generated_at: str,
        status: str | None = None,
        cached: bool = False,
    ) -> AiMeta:
        return AiMeta(
            provider=result.provider,
            model=result.model,
            real_call=result.real_call,
            cached=cached,
            status=status or result.status,
            latency_ms=result.latency_ms,
            fallback_used=result.fallback_used,
            attempts=[
                AiAttemptMeta(
                    provider=attempt.provider,
                    model=attempt.model,
                    outcome=attempt.outcome,
                    latency_ms=attempt.latency_ms,
                    real_call=attempt.real_call,
                    task=attempt.task,
                    error=attempt.error,
                )
                for attempt in result.attempts
            ],
            generated_at=generated_at,
        )

    def _combine_ai_meta(
        self,
        *items: tuple[str, JsonLlmResult],
        generated_at: str,
    ) -> AiMeta:
        if not items:
            return AiMeta(
                provider="unknown",
                model="unknown",
                real_call=False,
                cached=False,
                status="unavailable",
                latency_ms=0,
                fallback_used=False,
                attempts=[],
                generated_at=generated_at,
            )
        final_result = items[-1][1]
        attempts: list[AiAttemptMeta] = []
        total_latency = 0
        fallback_used = False
        real_call = False
        for task, result in items:
            total_latency += result.latency_ms
            fallback_used = fallback_used or result.fallback_used
            real_call = real_call or result.real_call
            for attempt in result.attempts:
                attempts.append(
                    AiAttemptMeta(
                        provider=attempt.provider,
                        model=attempt.model,
                        outcome=attempt.outcome,
                        latency_ms=attempt.latency_ms,
                        real_call=attempt.real_call,
                        task=task,
                        error=attempt.error,
                    )
                )
        return AiMeta(
            provider=final_result.provider,
            model=final_result.model,
            real_call=real_call,
            cached=False,
            status=final_result.status,
            latency_ms=total_latency,
            fallback_used=fallback_used,
            attempts=attempts,
            generated_at=generated_at,
        )

    def _merge_ai_meta_records(
        self,
        *items: tuple[str, AiMeta],
        generated_at: str,
    ) -> AiMeta:
        if not items:
            return AiMeta(
                provider="unknown",
                model="unknown",
                real_call=False,
                cached=False,
                status="unavailable",
                latency_ms=0,
                fallback_used=False,
                attempts=[],
                generated_at=generated_at,
            )

        final_meta = items[-1][1]
        attempts: list[AiAttemptMeta] = []
        total_latency = 0
        fallback_used = False
        real_call = False
        cached = False
        for task, meta in items:
            total_latency += meta.latency_ms
            fallback_used = fallback_used or meta.fallback_used
            real_call = real_call or meta.real_call
            cached = cached or meta.cached
            for attempt in meta.attempts:
                attempts.append(
                    attempt.model_copy(
                        update={
                            "task": attempt.task or task,
                        }
                    )
                )

        return AiMeta(
            provider=final_meta.provider,
            model=final_meta.model,
            real_call=real_call,
            cached=cached,
            status=final_meta.status,
            latency_ms=total_latency,
            fallback_used=fallback_used,
            attempts=attempts,
            generated_at=generated_at,
        )

    def _with_cached_ai_meta(self, response: Any) -> Any:
        ai_meta = getattr(response, "ai_meta", None)
        if ai_meta is None:
            return response
        return response.model_copy(
            update={
                "ai_meta": ai_meta.model_copy(
                    update={
                        "cached": True,
                        "status": "cached",
                    }
                )
            }
        )

    def classify_manager_chat_intent(self, *, message: str) -> ManagerChatClassification:
        classification, _ = self.classify_manager_chat_intent_with_meta(message=message)
        return classification

    def classify_manager_chat_intent_with_meta(
        self,
        *,
        message: str,
    ) -> tuple[ManagerChatClassification, AiMeta]:
        prompt = f"""
You are classifying a manager's question about DoorDrill sales training data.
Question: "{message}"

Respond with JSON only:
{{
  "intent": one of ["team_performance", "rep_specific", "scenario_analysis", "coaching_effectiveness", "risk_alerts", "comparison", "general"],
  "rep_name_mentioned": string | null,
  "scenario_mentioned": string | null,
  "category_mentioned": string | null
}}
""".strip()

        generated_at = datetime.now(timezone.utc).isoformat()
        result = self._call_manager_ai_json(
            system_prompt="You classify manager analytics questions. Return only valid JSON.",
            user_prompt=prompt,
            max_tokens=180,
            task="manager_chat_classification",
            fast=True,
            validator=ManagerChatClassification.model_validate,
        )
        classification = result.payload
        return classification, self._ai_meta_from_result(result, generated_at=generated_at)

    def answer_manager_chat(
        self,
        *,
        period_days: int,
        message: str,
        conversation_history: list[dict[str, str]],
        relevant_data: dict[str, Any],
    ) -> ManagerChatAnswerContent:
        content, _ = self.answer_manager_chat_with_meta(
            period_days=period_days,
            message=message,
            conversation_history=conversation_history,
            relevant_data=relevant_data,
        )
        return content

    def answer_manager_chat_with_meta(
        self,
        *,
        period_days: int,
        message: str,
        conversation_history: list[dict[str, str]],
        relevant_data: dict[str, Any],
    ) -> tuple[ManagerChatAnswerContent, AiMeta]:
        serialized_data = json.dumps(relevant_data, default=str, ensure_ascii=True)
        serialized_history = json.dumps(conversation_history[-12:], ensure_ascii=True)
        prompt = f"""
You are an expert sales performance analyst for DoorDrill, a D2D sales training platform.
You are answering a manager's question about their team's training performance.

Team data (last {period_days} days):
{serialized_data}

Conversation history:
{serialized_history}

Manager's question: "{message}"

Respond with JSON:
{{
  "answer": "your natural language answer (2-4 sentences, direct and specific)",
  "key_metric": "the single most relevant number or stat that answers the question",
  "key_metric_label": "label for the metric",
  "follow_up_suggestions": ["2-3 follow-up questions the manager might want to ask next"],
  "action_suggestion": "a concrete action the manager should take (1 sentence, optional, can be null)",
  "data_points": [{{"label": "stat name", "value": "stat value"}}]
}}
""".strip()

        generated_at = datetime.now(timezone.utc).isoformat()
        result = self._call_manager_ai_json(
            system_prompt="You are a precise manager analytics copilot. Return only valid JSON.",
            user_prompt=prompt,
            max_tokens=700,
            task="manager_chat_answer",
            validator=ManagerChatAnswerContent.model_validate,
        )
        content = result.payload

        answer = ManagerChatAnswerContent(
            answer=content.answer,
            key_metric=content.key_metric,
            key_metric_label=content.key_metric_label,
            follow_up_suggestions=content.follow_up_suggestions[:3],
            action_suggestion=content.action_suggestion,
            data_points=content.data_points[:4],
        )
        return answer, self._ai_meta_from_result(result, generated_at=generated_at)

    def answer_company_material_question(
        self,
        *,
        question: str,
        sources: list[RetrievedChunk],
    ) -> tuple[str, AiMeta]:
        if not sources:
            generated_at = datetime.now(timezone.utc).isoformat()
            return (
                "The uploaded company training material does not address that question.",
                AiMeta(
                    provider="retrieval_only",
                    model="none",
                    real_call=False,
                    cached=False,
                    status="no_data",
                    latency_ms=0,
                    fallback_used=False,
                    attempts=[],
                    generated_at=generated_at,
                ),
            )

        formatted_sources = self.document_retrieval_service.format_for_prompt(sources, max_tokens=1400)
        prompt = f"""
Answer the manager's question using only the provided company training material.
If the material does not answer the question, say so directly.
Do not invent advice, policies, or details that are not stated in the material.

Question: "{question.strip()}"

Provided company training material:
{formatted_sources}

Respond with JSON only:
{{
  "answer": "2-4 sentence answer grounded only in the provided material"
}}
""".strip()

        generated_at = datetime.now(timezone.utc).isoformat()
        result = self._call_manager_ai_json(
            system_prompt="You answer questions strictly from provided company training material. Return only valid JSON.",
            user_prompt=prompt,
            max_tokens=320,
            task="knowledge_answer",
            validator=lambda payload: payload
            if isinstance(payload, dict) and isinstance(payload.get("answer"), str) and payload.get("answer", "").strip()
            else (_ for _ in ()).throw(ValueError("answer_missing")),
        )

        content = result.payload
        answer = str(content["answer"]).strip()
        return answer, self._ai_meta_from_result(result, generated_at=generated_at)

    def _get_company_training_context(
        self,
        db: Session,
        *,
        org_id: str | None,
        topic: str,
        context_hint: str = "",
        k: int = 3,
        min_score: float = 0.68,
        max_tokens: int = 900,
    ) -> str | None:
        if not org_id:
            return None
        cache_key = self.company_training_context_cache.make_key(
            "company-training-context",
            {
                "org_id": org_id,
                "topic": topic,
                "context_hint": context_hint,
                "k": k,
                "min_score": min_score,
                "max_tokens": max_tokens,
            },
        )
        cached = self.company_training_context_cache.get_json(cache_key)
        if cached is not None:
            return cached.get("formatted_context")

        chunks = self.document_retrieval_service.retrieve_for_topic(
            db,
            org_id=org_id,
            topic=topic,
            context_hint=context_hint,
            k=k,
            min_score=min_score,
        )
        if not chunks:
            self.company_training_context_cache.set_json(cache_key, {"formatted_context": None})
            return None
        formatted = self.document_retrieval_service.format_for_prompt(chunks, max_tokens=max_tokens)
        result = formatted or None
        self.company_training_context_cache.set_json(cache_key, {"formatted_context": result})
        return result

    def generate_rep_insight(self, db: Session, *, rep: User, period_days: int) -> RepInsightResponse:
        cache_key = self.rep_insight_cache.make_key(
            "rep-insight",
            {
                "rep_id": rep.id,
                "period_days": period_days,
                **self._manager_ai_cache_signature(),
            },
        )
        cached = self.rep_insight_cache.get_json(cache_key)
        if cached is not None:
            return self._with_cached_ai_meta(RepInsightResponse.model_validate(cached))
        coaching_system_prefix = self._get_coaching_system_prefix(db, rep.org_id)

        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        rows = db.execute(
            select(
                DrillSession.id.label("session_id"),
                DrillSession.started_at.label("started_at"),
                Scorecard.overall_score.label("overall_score"),
                Scorecard.category_scores.label("category_scores"),
                Scorecard.weakness_tags.label("weakness_tags"),
                Scorecard.highlights.label("highlights"),
                Scorecard.ai_summary.label("ai_summary"),
                Scenario.name.label("scenario_name"),
                Scenario.difficulty.label("scenario_difficulty"),
            )
            .join(Scorecard, Scorecard.session_id == DrillSession.id)
            .join(Scenario, Scenario.id == DrillSession.scenario_id)
            .where(DrillSession.rep_id == rep.id, DrillSession.started_at >= cutoff)
            .order_by(DrillSession.started_at.desc())
            .limit(30)
        ).mappings().all()

        if not rows:
            raise AiCoachingDataUnavailableError("No scored sessions are available for this rep in the selected period")

        recent_session_ids = [str(row["session_id"]) for row in rows if row["session_id"]]
        detailed_sessions = db.scalars(
            select(DrillSession)
            .where(DrillSession.id.in_(recent_session_ids))
            .order_by(DrillSession.started_at.asc(), DrillSession.created_at.asc())
            .options(
                selectinload(DrillSession.scorecard),
                selectinload(DrillSession.turns),
                selectinload(DrillSession.events),
            )
        ).all()
        scenarios_by_id = {
            scenario.id: scenario
            for scenario in db.scalars(
                select(Scenario).where(Scenario.id.in_({session.scenario_id for session in detailed_sessions}))
            ).all()
        }
        recent_snapshots = [
            self.adaptive_training_service._build_session_snapshot(
                session=session,
                scenario=scenarios_by_id.get(session.scenario_id),
            )
            for session in detailed_sessions
            if session.scorecard is not None
        ]
        adaptive_plan = self.adaptive_training_service.build_plan(db, rep_id=rep.id)
        adaptive_skill_profile = list(adaptive_plan.get("skill_profile") or [])
        cohort_benchmarks = self.predictive_modeling_service.get_rep_benchmarks(db, rep_id=rep.id)
        cohort_benchmark_summary = "; ".join(
            (
                f"{item['skill']}: {item['percentile_in_cohort']:.0f}th percentile"
                for item in cohort_benchmarks.get("skills", [])
                if item.get("percentile_in_cohort") is not None
            )
        ) or "No cohort benchmark data available."
        risk_signal = self.predictive_modeling_service.get_at_risk_reps(
            db,
            manager_id=rep.team.manager_id if rep.team is not None and rep.team.manager_id else "",
            org_id=rep.org_id,
            min_risk_level="low",
        ) if rep.team is not None and rep.team.manager_id else []
        rep_risk = next((item for item in risk_signal if item.get("rep_id") == rep.id), None)
        readiness_trajectory = self._compute_readiness_trajectory(
            recent_snapshots,
            adaptive_skill_profile,
        )
        emotion_recovery_average = round(
            self._mean(
                snapshot.get("emotion_recovery", 0.0)
                for snapshot in recent_snapshots
                if isinstance(snapshot.get("emotion_recovery"), (int, float))
            ),
            2,
        )
        override_signal = self._load_override_signal(
            db,
            rep_id=rep.id,
            cutoff=cutoff,
        )

        scores = [float(row["overall_score"]) for row in rows if row["overall_score"] is not None]
        average_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        category_samples: dict[str, list[float]] = defaultdict(list)
        weakness_counts: Counter[str] = Counter()
        recent_summaries: list[dict[str, Any]] = []
        scenario_samples: list[dict[str, Any]] = []

        for row in rows:
            category_scores = row["category_scores"] or {}
            for raw_key, normalized_key in RUBRIC_CATEGORY_KEYS.items():
                value = _score_value(category_scores.get(raw_key))
                if value is not None:
                    category_samples[normalized_key].append(value)
            weakness_counts.update(tag for tag in (row["weakness_tags"] or []) if isinstance(tag, str) and tag.strip())
            recent_summaries.append(
                {
                    "session_id": row["session_id"],
                    "scenario_name": row["scenario_name"],
                    "scenario_difficulty": row["scenario_difficulty"],
                    "summary": row["ai_summary"],
                }
            )
            scenario_samples.append(
                {
                    "session_id": row["session_id"],
                    "scenario_name": row["scenario_name"],
                    "scenario_difficulty": row["scenario_difficulty"],
                    "overall_score": row["overall_score"],
                }
            )

        category_averages = {
            "opening": round(sum(category_samples.get("opening", [])) / max(len(category_samples.get("opening", [])), 1), 2)
            if category_samples.get("opening")
            else 0.0,
            "pitch": round(sum(category_samples.get("pitch", [])) / max(len(category_samples.get("pitch", [])), 1), 2)
            if category_samples.get("pitch")
            else 0.0,
            "objection_handling": round(
                sum(category_samples.get("objection_handling", [])) / max(len(category_samples.get("objection_handling", [])), 1),
                2,
            )
            if category_samples.get("objection_handling")
            else 0.0,
            "closing": round(sum(category_samples.get("closing", [])) / max(len(category_samples.get("closing", [])), 1), 2)
            if category_samples.get("closing")
            else 0.0,
            "professionalism": round(
                sum(category_samples.get("professionalism", [])) / max(len(category_samples.get("professionalism", [])), 1),
                2,
            )
            if category_samples.get("professionalism")
            else 0.0,
        }

        trend_rows = list(reversed(rows[:10]))
        trend_scores = [float(row["overall_score"]) for row in trend_rows if row["overall_score"] is not None]
        trend_slope = round(_linear_regression_slope(trend_scores), 3)
        trend_delta = round((trend_scores[-1] - trend_scores[0]) if len(trend_scores) >= 2 else 0.0, 2)
        if trend_delta > 0.25:
            trend_direction = "improving"
        elif trend_delta < -0.25:
            trend_direction = "declining"
        else:
            trend_direction = "flat"

        top_weakness_tags = [tag for tag, _ in weakness_counts.most_common(3)]
        company_training_context = self._get_company_training_context(
            db,
            org_id=rep.org_id,
            topic=f"coaching {' '.join(top_weakness_tags)} technique improvement".strip(),
            context_hint=f"rep {rep.name} weak areas {' '.join(adaptive_plan.get('weakest_skills', []))}".strip(),
            k=3,
            min_score=0.68,
            max_tokens=900,
        )
        below_threshold_count = sum(1 for score in scores if score < 6.0)
        last_three_summaries = "\n".join(
            f"- {item['scenario_name']} (difficulty {item['scenario_difficulty']}): {item['summary']}"
            for item in recent_summaries[:3]
        ) or "- No recent AI summaries available."

        prompt = f"""
You are an expert D2D sales coach analyzing a rep's training data.

Rep data:
- Name: {rep.name}
- Sessions analyzed: {len(rows)}
- Average score: {average_score}/10
- Score trend: {trend_direction} ({trend_delta:+.1f} over last 10 sessions)
- Category averages: Opening {category_averages['opening']}/10, Pitch {category_averages['pitch']}/10, Objection Handling {category_averages['objection_handling']}/10, Closing {category_averages['closing']}/10, Professionalism {category_averages['professionalism']}/10
- Top weakness tags: {", ".join(top_weakness_tags) if top_weakness_tags else "None identified"}
- Adaptive skill profile: {json.dumps(adaptive_skill_profile, default=str)}
- Adaptive readiness score: {adaptive_plan.get('readiness_score', 0.0)}/10
- Recommended difficulty: {adaptive_plan.get('recommended_difficulty')}
- Adaptive weakest skills: {", ".join(adaptive_plan.get('weakest_skills', [])) or "None identified"}
- Cohort benchmarks: {cohort_benchmark_summary}
- Emotion recovery average across recent sessions: {emotion_recovery_average}/10
- Override signal: {json.dumps(override_signal, default=str)}
- Readiness trajectory: {json.dumps(readiness_trajectory, default=str)}
- Risk level: {(rep_risk or {}).get('risk_level', 'low')}
- Risk flags: {", ".join((rep_risk or {}).get('triggered_alerts', [])) or "none"}. The manager should be aware of these signals.
- Recent AI session summaries:
{last_three_summaries}

{"Company training material relevant to this rep's weak areas:\n" + company_training_context + "\n\nWhen writing the coaching_script, reference what the company's own material says\nabout improving these skills. Quote or paraphrase it specifically — don't give generic advice." if company_training_context else ""}

Provide a coaching analysis in this exact JSON format:
{{
  "headline": "one sentence diagnosis (max 15 words)",
  "primary_weakness": "the single most important area to fix",
  "root_cause": "why this weakness likely exists (2 sentences)",
  "drill_recommendation": "specific scenario type and difficulty to assign next",
  "coaching_script": "3-4 sentences the manager should say directly to this rep",
  "expected_improvement": "what should improve and in how many sessions if coaching works"
}}
""".strip()

        result = self._call_manager_ai_json(
            system_prompt=(
                f"{coaching_system_prefix}\n\n"
                "You are a precise sales coaching analyst. Return only valid JSON."
            ),
            user_prompt=prompt,
            max_tokens=700,
            task="rep_insight",
            validator=RepInsightContent.model_validate,
        )
        content = result.payload

        data_summary = {
            "period_days": period_days,
            "session_count": len(rows),
            "average_score": average_score,
            "category_averages": category_averages,
            "top_weakness_tags": top_weakness_tags,
            "below_six_count": below_threshold_count,
            "trend": {
                "direction": trend_direction,
                "delta": trend_delta,
                "slope": trend_slope,
                "session_count": len(trend_scores),
            },
            "recent_session_summaries": recent_summaries[:3],
            "recent_scenarios": scenario_samples[:10],
            "adaptive_plan": {
                "readiness_score": adaptive_plan.get("readiness_score"),
                "recommended_difficulty": adaptive_plan.get("recommended_difficulty"),
                "weakest_skills": adaptive_plan.get("weakest_skills", []),
            },
            "cohort_benchmarks": cohort_benchmarks,
            "emotion_recovery_average": emotion_recovery_average,
            "override_signal": override_signal,
            "readiness_trajectory": readiness_trajectory,
            "risk_signal": rep_risk or {
                "risk_level": "low",
                "triggered_alerts": [],
            },
        }
        generated_at = datetime.now(timezone.utc).isoformat()
        response = RepInsightResponse(
            rep_id=rep.id,
            rep_name=rep.name,
            generated_at=generated_at,
            data_summary=data_summary,
            ai_meta=self._ai_meta_from_result(result, generated_at=generated_at),
            **content.model_copy(
                update={
                    "readiness_trajectory": readiness_trajectory,
                    "override_signal": override_signal,
                    "adaptive_skill_profile": adaptive_skill_profile,
                    "risk_level": (rep_risk or {}).get("risk_level"),
                    "triggered_alerts": list((rep_risk or {}).get("triggered_alerts") or []),
                }
            ).model_dump(),
        )
        self.rep_insight_cache.set_json(cache_key, response.model_dump(mode="json"))
        return response

    def generate_one_on_one_prep(
        self,
        db: Session,
        *,
        rep: User,
        manager: User,
        period_days: int,
    ) -> OneOnOnePrepResponse:
        cache_key = self.one_on_one_prep_cache.make_key(
            "one-on-one-prep",
            {
                "manager_id": manager.id,
                "rep_id": rep.id,
                "period_days": period_days,
                **self._manager_ai_cache_signature(),
            },
        )
        cached = self.one_on_one_prep_cache.get_json(cache_key)
        if cached is not None:
            return self._with_cached_ai_meta(OneOnOnePrepResponse.model_validate(cached))
        coaching_system_prefix = self._get_coaching_system_prefix(db, rep.org_id)

        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        sessions = db.scalars(
            select(DrillSession)
            .join(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(
                DrillSession.rep_id == rep.id,
                DrillSession.started_at >= cutoff,
            )
            .order_by(DrillSession.started_at.desc(), DrillSession.created_at.desc())
            .limit(5)
            .options(
                selectinload(DrillSession.scorecard).selectinload(Scorecard.coaching_notes),
                selectinload(DrillSession.turns),
                selectinload(DrillSession.events),
            )
        ).all()
        if not sessions:
            raise AiCoachingDataUnavailableError("No scored sessions are available for this rep in the selected period")

        outcomes = db.scalars(
            select(AdaptiveRecommendationOutcome)
            .where(
                AdaptiveRecommendationOutcome.rep_id == rep.id,
                AdaptiveRecommendationOutcome.created_at >= cutoff,
            )
            .order_by(AdaptiveRecommendationOutcome.outcome_written_at.desc(), AdaptiveRecommendationOutcome.created_at.desc())
            .limit(5)
        ).all()

        session_ids = [session.id for session in sessions]
        labels = db.scalars(
            select(OverrideLabel)
            .where(OverrideLabel.session_id.in_(session_ids))
            .order_by(OverrideLabel.created_at.desc())
        ).all() if session_ids else []
        labels_by_session: dict[str, list[OverrideLabel]] = defaultdict(list)
        for label in labels:
            labels_by_session[label.session_id].append(label)

        scenario_ids = {session.scenario_id for session in sessions}
        scenario_ids.update(
            str(outcome.recommended_scenario_id)
            for outcome in outcomes
            if outcome.recommended_scenario_id
        )
        scenarios_by_id = {
            scenario.id: scenario
            for scenario in db.scalars(select(Scenario).where(Scenario.id.in_(scenario_ids))).all()
        } if scenario_ids else {}

        chronological_sessions = sorted(
            sessions,
            key=lambda session: (
                session.started_at or session.created_at,
                session.created_at,
            ),
        )
        recent_snapshots = [
            self.adaptive_training_service._build_session_snapshot(
                session=session,
                scenario=scenarios_by_id.get(session.scenario_id),
            )
            for session in chronological_sessions
            if session.scorecard is not None
        ]
        adaptive_plan = self.adaptive_training_service.build_plan(db, rep_id=rep.id)
        readiness_trajectory = self._compute_readiness_trajectory(
            recent_snapshots,
            adaptive_plan.get("skill_profile") or [],
        )
        override_signal = self._load_override_signal(
            db,
            rep_id=rep.id,
            cutoff=cutoff,
        )
        note_tag_counts: Counter[str] = Counter()
        recent_sessions_payload: list[dict[str, Any]] = []

        for session in sessions:
            scorecard = session.scorecard
            if scorecard is None:
                continue
            scenario = scenarios_by_id.get(session.scenario_id)
            normalized_scores = self._normalize_category_scores(scorecard.category_scores)
            coaching_notes = [
                {
                    "note": note.note,
                    "visible_to_rep": note.visible_to_rep,
                    "weakness_tags": list(note.weakness_tags or []),
                    "created_at": note.created_at.isoformat() if note.created_at else None,
                }
                for note in scorecard.coaching_notes[:2]
            ]
            for note in scorecard.coaching_notes:
                note_tag_counts.update(
                    tag for tag in (note.weakness_tags or []) if isinstance(tag, str) and tag.strip()
                )

            recent_sessions_payload.append(
                {
                    "session_id": session.id,
                    "started_at": session.started_at.isoformat() if session.started_at else None,
                    "scenario_name": scenario.name if scenario else "Unknown Scenario",
                    "scenario_difficulty": int(scenario.difficulty) if scenario else None,
                    "overall_score": round(float(scorecard.overall_score), 2),
                    "category_scores": normalized_scores,
                    "weakness_tags": list(scorecard.weakness_tags or []),
                    "ai_summary": scorecard.ai_summary,
                    "coaching_notes": coaching_notes,
                    "override_labels": [
                        {
                            "delta": round(label.override_delta_overall, 2),
                            "reason": label.override_reason_text,
                            "most_overridden_category": self._most_overridden_category([label]),
                            "created_at": label.created_at.isoformat() if label.created_at else None,
                        }
                        for label in labels_by_session.get(session.id, [])[:2]
                    ],
                }
            )

        recent_outcomes_payload = [
            {
                "scenario_name": (
                    scenarios_by_id[outcome.recommended_scenario_id].name
                    if outcome.recommended_scenario_id in scenarios_by_id
                    else outcome.recommended_scenario_id
                ),
                "recommended_difficulty": outcome.recommended_difficulty,
                "focus_skills": list(outcome.recommended_focus_skills or []),
                "recommendation_success": outcome.recommendation_success,
                "skill_delta": dict(outcome.skill_delta or {}),
                "baseline_overall_score": outcome.baseline_overall_score,
                "outcome_overall_score": outcome.outcome_overall_score,
                "outcome_written_at": (
                    outcome.outcome_written_at.isoformat()
                    if outcome.outcome_written_at
                    else outcome.created_at.isoformat() if outcome.created_at else None
                ),
            }
            for outcome in outcomes
        ]
        latest_recommendation = next(iter(adaptive_plan.get("recommended_scenarios") or []), {})
        company_training_context = self._get_company_training_context(
            db,
            org_id=rep.org_id,
            topic=f"1:1 coaching {' '.join(adaptive_plan.get('weakest_skills', []))} conversation technique".strip(),
            context_hint=f"manager {manager.name} coaching rep {rep.name}".strip(),
            k=3,
            min_score=0.68,
            max_tokens=900,
        )
        prompt = f"""
You are an expert D2D sales manager preparing for a 1:1 coaching conversation.

Manager:
- Name: {manager.name}

Rep:
- Name: {rep.name}
- Period analyzed: {period_days} days
- Adaptive plan: {json.dumps(adaptive_plan, default=str)}
- Readiness trajectory: {json.dumps(readiness_trajectory, default=str)}
- Override signal: {json.dumps(override_signal, default=str)}
- Coaching note themes: {json.dumps(note_tag_counts.most_common(3), default=str)}
- Last 5 sessions: {json.dumps(recent_sessions_payload, default=str)}
- Recent adaptive recommendation outcomes: {json.dumps(recent_outcomes_payload, default=str)}
- Current top recommended next scenario: {json.dumps(latest_recommendation, default=str)}

{"Company training material relevant to this rep's weak areas:\n" + company_training_context + "\n\nWhen writing the prep, reference what the company's own material says\nabout improving these skills. Quote or paraphrase it specifically — don't give generic advice." if company_training_context else ""}

Return JSON in this exact shape:
{{
  "discussion_topics": [
    {{"topic": "string", "evidence": "1 sentence with specific numbers", "suggested_opener": "exact words the manager should say"}},
    {{"topic": "string", "evidence": "1 sentence with specific numbers", "suggested_opener": "exact words the manager should say"}},
    {{"topic": "string", "evidence": "1 sentence with specific numbers", "suggested_opener": "exact words the manager should say"}}
  ],
  "strength_to_acknowledge": {{"skill": "string", "what_to_say": "1-2 sentences"}},
  "pattern_to_challenge": {{"skill": "string", "pattern": "description with concrete evidence", "what_to_say": "1-2 sentences"}},
  "suggested_next_scenario": {{"scenario_type": "string", "difficulty": 1, "rationale": "1 sentence with specific rationale"}},
  "readiness_summary": "one sentence on where this rep stands overall right now"
}}

Requirements:
- `discussion_topics` must be exactly 3 items ordered by priority.
- Every evidence sentence must cite real numbers from the provided data.
- Avoid generic coaching language. Make each opener feel like something a manager would actually say in a 1:1.
""".strip()

        result = self._call_manager_ai_json(
            system_prompt=(
                f"{coaching_system_prefix}\n\n"
                "You are a precise manager prep copilot. Return only valid JSON."
            ),
            user_prompt=prompt,
            max_tokens=900,
            task="one_on_one_prep",
            validator=lambda payload: OneOnOnePrepContent.model_validate(
                {
                    **payload,
                    "discussion_topics": list((payload or {}).get("discussion_topics") or [])[:3]
                    if isinstance(payload, dict)
                    else payload,
                }
            ),
        )
        content = result.payload
        data_summary = {
            "period_days": period_days,
            "adaptive_plan": {
                "readiness_score": adaptive_plan.get("readiness_score"),
                "recommended_difficulty": adaptive_plan.get("recommended_difficulty"),
                "weakest_skills": adaptive_plan.get("weakest_skills", []),
            },
            "readiness_trajectory": readiness_trajectory,
            "override_signal": override_signal,
            "coaching_note_themes": [
                {"tag": tag, "count": count}
                for tag, count in note_tag_counts.most_common(3)
            ],
            "recent_sessions": recent_sessions_payload,
            "adaptive_outcomes": recent_outcomes_payload,
        }
        generated_at = datetime.now(timezone.utc).isoformat()
        response = OneOnOnePrepResponse(
            manager_id=manager.id,
            rep_id=rep.id,
            rep_name=rep.name,
            period_days=period_days,
            generated_at=generated_at,
            data_summary=data_summary,
            ai_meta=self._ai_meta_from_result(result, generated_at=generated_at),
            **content.model_dump(),
        )
        self.one_on_one_prep_cache.set_json(cache_key, response.model_dump(mode="json"))
        return response

    def generate_weekly_team_briefing(
        self,
        db: Session,
        *,
        manager: User,
        reps: list[User],
    ) -> WeeklyTeamBriefingResponse:
        cache_key = self.weekly_team_briefing_cache.make_key(
            "weekly-team-briefing",
            {
                "manager_id": manager.id,
                **self._manager_ai_cache_signature(),
            },
        )
        cached = self.weekly_team_briefing_cache.get_json(cache_key)
        if cached is not None:
            return self._with_cached_ai_meta(WeeklyTeamBriefingResponse.model_validate(cached))
        coaching_system_prefix = self._get_coaching_system_prefix(db, manager.org_id)

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        rep_ids = [rep.id for rep in reps]
        if not rep_ids:
            raise AiCoachingDataUnavailableError("No reps are available for this manager")

        sessions = db.scalars(
            select(DrillSession)
            .join(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(
                DrillSession.rep_id.in_(rep_ids),
                DrillSession.started_at >= cutoff,
            )
            .order_by(DrillSession.started_at.desc(), DrillSession.created_at.desc())
            .options(
                selectinload(DrillSession.scorecard),
                selectinload(DrillSession.turns),
                selectinload(DrillSession.events),
            )
        ).all()
        if not sessions:
            raise AiCoachingDataUnavailableError("No scored sessions are available for this team in the last 7 days")

        sessions_by_rep: dict[str, list[DrillSession]] = defaultdict(list)
        weakness_counts: Counter[str] = Counter()
        for session in sessions:
            sessions_by_rep[session.rep_id].append(session)
            if session.scorecard is not None:
                weakness_counts.update(
                    tag for tag in (session.scorecard.weakness_tags or []) if isinstance(tag, str) and tag.strip()
                )

        active_reps = [
            rep
            for rep in reps
            if sessions_by_rep.get(rep.id)
        ]
        active_reps.sort(
            key=lambda rep: (
                len(sessions_by_rep.get(rep.id, [])),
                max(
                    (
                        (session.started_at or session.created_at)
                        for session in sessions_by_rep.get(rep.id, [])
                    ),
                    default=datetime.min.replace(tzinfo=timezone.utc),
                ),
            ),
            reverse=True,
        )
        capped_reps = active_reps[:8]
        capped_rep_ids = [rep.id for rep in capped_reps]

        fact_rows = db.scalars(
            select(FactRepDaily)
            .where(
                FactRepDaily.manager_id == manager.id,
                FactRepDaily.rep_id.in_(capped_rep_ids),
                FactRepDaily.session_date >= cutoff.date(),
            )
            .order_by(FactRepDaily.session_date.asc())
        ).all() if capped_rep_ids else []
        facts_by_rep: dict[str, list[FactRepDaily]] = defaultdict(list)
        for row in fact_rows:
            facts_by_rep[row.rep_id].append(row)

        rep_briefs: list[dict[str, Any]] = []
        for rep in capped_reps:
            rep_sessions = sorted(
                sessions_by_rep.get(rep.id, []),
                key=lambda session: (
                    session.started_at or session.created_at,
                    session.created_at,
                ),
            )
            adaptive_plan = self.adaptive_training_service.build_plan(db, rep_id=rep.id)
            scores = [
                float(session.scorecard.overall_score)
                for session in rep_sessions
                if session.scorecard is not None and session.scorecard.overall_score is not None
            ]
            trend_delta = round(scores[-1] - scores[0], 2) if len(scores) >= 2 else 0.0
            week_average = round(self._mean(scores), 2) if scores else 0.0
            weakest_skills = list(adaptive_plan.get("weakest_skills") or [])
            weakness_snapshot = {
                skill: round(float(node.get("score", 0.0)), 2)
                for skill, node in self._normalize_skill_profile(adaptive_plan.get("skill_profile") or []).items()
                if skill in weakest_skills
            }
            latest_session = rep_sessions[-1] if rep_sessions else None
            latest_scorecard = latest_session.scorecard if latest_session is not None else None
            warehouse_summary = {
                "days_tracked": len(facts_by_rep.get(rep.id, [])),
                "session_count": sum(row.session_count for row in facts_by_rep.get(rep.id, [])),
                "avg_score": round(
                    self._mean(
                        row.avg_score for row in facts_by_rep.get(rep.id, [])
                        if row.avg_score is not None
                    ),
                    2,
                ) if facts_by_rep.get(rep.id) else None,
                "avg_objection_handling": round(
                    self._mean(
                        row.avg_objection_handling for row in facts_by_rep.get(rep.id, [])
                        if row.avg_objection_handling is not None
                    ),
                    2,
                ) if facts_by_rep.get(rep.id) else None,
                "avg_closing_technique": round(
                    self._mean(
                        row.avg_closing_technique for row in facts_by_rep.get(rep.id, [])
                        if row.avg_closing_technique is not None
                    ),
                    2,
                ) if facts_by_rep.get(rep.id) else None,
                "override_count": sum(row.override_count for row in facts_by_rep.get(rep.id, [])),
                "coaching_note_count": sum(row.coaching_note_count for row in facts_by_rep.get(rep.id, [])),
            }
            rep_briefs.append(
                {
                    "rep_id": rep.id,
                    "rep_name": rep.name,
                    "session_count": len(rep_sessions),
                    "average_score": week_average,
                    "trend_delta": trend_delta,
                    "readiness_score": adaptive_plan.get("readiness_score"),
                    "recommended_difficulty": adaptive_plan.get("recommended_difficulty"),
                    "weakest_skills": weakest_skills,
                    "weakest_skill_scores": weakness_snapshot,
                    "latest_summary": latest_scorecard.ai_summary if latest_scorecard is not None else None,
                    "latest_weakness_tags": list(latest_scorecard.weakness_tags or []) if latest_scorecard is not None else [],
                    "warehouse_summary": warehouse_summary,
                }
            )

        at_risk_reps = self.predictive_modeling_service.get_at_risk_reps(
            db,
            manager_id=manager.id,
            org_id=manager.org_id,
            min_risk_level="medium",
        )
        manager_coaching_effectiveness = self.predictive_modeling_service.get_manager_impact_summary(
            db,
            manager_id=manager.id,
        )
        at_risk_by_rep_id = {item["rep_id"]: item for item in at_risk_reps}
        for brief in rep_briefs:
            risk = at_risk_by_rep_id.get(brief["rep_id"])
            if risk:
                brief["risk_signal"] = {
                    "risk_level": risk.get("risk_level"),
                    "risk_score": risk.get("risk_score"),
                    "triggered_alerts": risk.get("triggered_alerts", []),
                }

        team_average_score = round(
            self._mean(item["average_score"] for item in rep_briefs if isinstance(item.get("average_score"), (int, float))),
            2,
        )
        shared_weakness = weakness_counts.most_common(1)[0][0] if weakness_counts else "objection_handling"
        prompt = f"""
You are an expert sales manager preparing a weekly team briefing for a D2D training team.

Manager:
- Name: {manager.name}

Team data for the last 7 days:
- Rep summaries: {json.dumps(rep_briefs, default=str)}
- Team average score: {team_average_score}
- Most common weakness tag: {shared_weakness}
- At-risk reps from predictive scoring: {json.dumps(at_risk_reps[:3], default=str)}
- Your recent coaching interventions show {((manager_coaching_effectiveness.get('avg_score_delta') or 0.0)):+.2f} avg score delta with {(manager_coaching_effectiveness.get('positive_impact_rate') or 0.0):.0%} positive impact rate.

Return JSON in this exact shape:
{{
  "team_pulse": "2 sentences on overall team momentum this week",
  "standout_rep": {{"name": "string", "why": "1 sentence with specific stat"}},
  "needs_attention": [
    {{"name": "string", "concern": "1 sentence with specific stat"}},
    {{"name": "string", "concern": "1 sentence with specific stat"}}
  ],
  "shared_weakness": {{"skill": "string", "team_average": 0.0, "note": "1 sentence"}},
  "huddle_topic": {{"topic": "string", "suggested_talking_points": ["string", "string", "string"]}},
  "manager_action_items": ["string", "string"]
}}

Requirements:
- `needs_attention` must contain at most 2 reps.
- `manager_action_items` must be concrete and directly assignable, not vague.
- Every claim should be grounded in the supplied stats.
""".strip()

        result = self._call_manager_ai_json(
            system_prompt=(
                f"{coaching_system_prefix}\n\n"
                "You are a precise weekly team briefing copilot. Return only valid JSON."
            ),
            user_prompt=prompt,
            max_tokens=900,
            task="weekly_team_briefing",
            validator=WeeklyTeamBriefingContent.model_validate,
        )
        content_payload = result.payload.model_dump()
        content_payload["needs_attention"] = [
            {
                "name": next(
                    (
                        brief["rep_name"]
                        for brief in rep_briefs
                        if brief["rep_id"] == risk["rep_id"]
                    ),
                    risk["rep_id"],
                ),
                "concern": self._weekly_risk_concern_text(risk),
            }
            for risk in at_risk_reps[:2]
        ]

        generated_at = datetime.now(timezone.utc).isoformat()
        response = WeeklyTeamBriefingResponse.model_validate(
            {
                "manager_id": manager.id,
                "generated_at": generated_at,
                "data_summary": {
                    "period_days": 7,
                    "rep_count_considered": len(capped_reps),
                    "team_average_score": team_average_score,
                    "most_common_weakness_tag": shared_weakness,
                    "at_risk_reps": at_risk_reps[:5],
                    "manager_coaching_effectiveness": {
                        "avg_score_delta": manager_coaching_effectiveness.get("avg_score_delta"),
                        "positive_impact_rate": manager_coaching_effectiveness.get("positive_impact_rate"),
                    },
                    "rep_summaries": rep_briefs,
                },
                "ai_meta": self._ai_meta_from_result(result, generated_at=generated_at),
                **content_payload,
            }
        )
        self.weekly_team_briefing_cache.set_json(cache_key, response.model_dump(mode="json"))
        return response

    def _load_override_signal(
        self,
        db: Session,
        *,
        rep_id: str,
        cutoff: datetime,
    ) -> dict[str, Any]:
        labels = db.scalars(
            select(OverrideLabel)
            .join(DrillSession, DrillSession.id == OverrideLabel.session_id)
            .where(
                DrillSession.rep_id == rep_id,
                DrillSession.started_at >= cutoff,
                OverrideLabel.created_at >= cutoff,
            )
            .order_by(OverrideLabel.created_at.desc())
        ).all()

        mean_delta = round(
            self._mean(label.override_delta_overall for label in labels),
            2,
        ) if labels else 0.0
        return {
            "override_count": len(labels),
            "mean_delta": mean_delta,
            "most_overridden_category": self._most_overridden_category(labels),
        }

    def _most_overridden_category(self, labels: Sequence[OverrideLabel]) -> str | None:
        category_counts: Counter[str] = Counter()
        for label in labels:
            ai_scores = label.ai_category_scores or {}
            override_scores = label.override_category_scores or {}
            if not isinstance(ai_scores, dict) or not isinstance(override_scores, dict):
                continue

            for raw_key, override_value in override_scores.items():
                normalized_key = RUBRIC_CATEGORY_KEYS.get(raw_key, raw_key)
                ai_value = _score_value(ai_scores.get(raw_key))
                if ai_value is None:
                    fallback_key = next(
                        (key for key, value in RUBRIC_CATEGORY_KEYS.items() if value == normalized_key and key in ai_scores),
                        None,
                    )
                    ai_value = _score_value(ai_scores.get(fallback_key)) if fallback_key else None
                override_score = _score_value(override_value)
                if ai_value is None or override_score is None:
                    continue
                if abs(override_score - ai_value) >= 0.05:
                    category_counts[normalized_key] += 1

        if not category_counts:
            return None
        return category_counts.most_common(1)[0][0]

    def _compute_readiness_trajectory(
        self,
        snapshots: list[dict[str, Any]],
        skill_profile: list[dict[str, Any]] | dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        profile_map = self._normalize_skill_profile(skill_profile)
        if not profile_map:
            return {"sessions_to_readiness": None, "trajectory_per_skill": {}}

        slopes = {
            skill: _linear_regression_slope(
                [
                    float(snapshot["skills"][skill])
                    for snapshot in snapshots
                    if isinstance((snapshot.get("skills") or {}).get(skill), (int, float))
                ]
            )
            for skill in profile_map
        }
        target_skills = [
            skill
            for skill, node in profile_map.items()
            if float(node.get("score", 0.0)) < READINESS_THRESHOLD
        ]
        if not target_skills:
            return {
                "sessions_to_readiness": 0,
                "trajectory_per_skill": {
                    skill: round(float(node.get("score", 0.0)), 2)
                    for skill, node in profile_map.items()
                },
            }

        sessions_required: list[int] = []
        for skill in target_skills:
            current_score = float(profile_map[skill].get("score", 0.0))
            slope = slopes.get(skill, 0.0)
            if slope <= 0:
                projection_horizon = max(1, min(6, len(snapshots) or 1))
                return {
                    "sessions_to_readiness": None,
                    "trajectory_per_skill": {
                        current_skill: round(self._clamp_score(float(node.get("score", 0.0)) + (slopes.get(current_skill, 0.0) * projection_horizon)), 2)
                        for current_skill, node in profile_map.items()
                    },
                }
            sessions_required.append(max(0, math.ceil((READINESS_THRESHOLD - current_score) / slope)))

        sessions_to_readiness = max(sessions_required) if sessions_required else 0
        return {
            "sessions_to_readiness": sessions_to_readiness,
            "trajectory_per_skill": {
                skill: round(self._clamp_score(float(node.get("score", 0.0)) + (slopes.get(skill, 0.0) * sessions_to_readiness)), 2)
                for skill, node in profile_map.items()
            },
        }

    def _normalize_skill_profile(
        self,
        skill_profile: list[dict[str, Any]] | dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if isinstance(skill_profile, dict):
            return {
                str(skill): node
                for skill, node in skill_profile.items()
                if isinstance(node, dict)
            }
        return {
            str(node["skill"]): node
            for node in skill_profile
            if isinstance(node, dict) and isinstance(node.get("skill"), str)
        }

    def _mean(self, values: Sequence[float]) -> float:
        items = [float(value) for value in values]
        if not items:
            return 0.0
        return sum(items) / len(items)

    def _weekly_risk_concern_text(self, risk: dict[str, Any]) -> str:
        alerts = ", ".join(risk.get("triggered_alerts") or []) or "no explicit flags"
        risk_level = risk.get("risk_level") or "low"
        if risk.get("days_since_last_session") is not None:
            return (
                f"Risk is {risk_level} with flags {alerts}; the rep has been inactive for "
                f"{risk['days_since_last_session']} days."
            )
        if risk.get("decline_slope") is not None:
            return (
                f"Risk is {risk_level} with flags {alerts}; the current decline slope is "
                f"{risk['decline_slope']:.2f} per session."
            )
        return f"Risk is {risk_level} with flags {alerts}."

    def _clamp_score(self, value: float) -> float:
        return max(0.0, min(10.0, value))

    def _normalize_category_scores(self, category_scores: dict[str, Any] | None) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for raw_key, category_key in RUBRIC_CATEGORY_KEYS.items():
            value = _score_value((category_scores or {}).get(raw_key))
            if value is not None and category_key not in normalized:
                normalized[category_key] = round(value, 2)
        return normalized

    def generate_session_annotations(self, db: Session, *, session_id: str) -> SessionAnnotationsResponse:
        cache_key = self.session_annotations_cache.make_key(
            "session-annotations",
            {
                "session_id": session_id,
                **self._manager_ai_cache_signature(),
            },
        )
        cached = self.session_annotations_cache.get_json(cache_key)
        if cached is not None:
            return self._with_cached_ai_meta(SessionAnnotationsResponse.model_validate(cached))
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        org_id = session.rep.org_id if session is not None and session.rep is not None else None
        coaching_system_prefix = self._get_coaching_system_prefix(db, org_id)

        turns = db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())
        ).all()
        if not turns:
            raise AiCoachingDataUnavailableError("Transcript turns are not available for this session")

        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        if scorecard is None:
            raise AiCoachingDataUnavailableError("Scorecard is not available for this session")

        transcript = "\n".join(
            f'[TURN {turn.turn_index} | TURN_ID {turn.id}] {turn.speaker.value.upper()}: "{turn.text}"'
            for turn in turns
        )
        highlights = []
        for item in scorecard.highlights or []:
            if not isinstance(item, dict):
                continue
            note = item.get("note")
            highlight_type = item.get("type")
            if isinstance(note, str) and note.strip():
                highlights.append(f"- {highlight_type or 'note'}: {note}")
        prompt = f"""
You are a D2D sales training coach. Analyze this sales call transcript and identify the 3-5 most instructive moments - moments where the rep either did something particularly well or made a mistake that should be discussed in coaching.

Transcript:
{transcript}

Scorecard context:
- Overall score: {scorecard.overall_score}/10
- Weakness tags: {", ".join(scorecard.weakness_tags) if scorecard.weakness_tags else "None"}
- Highlights:
{chr(10).join(highlights) if highlights else "- None"}

Return JSON array:
[
  {{
    "turn_id": "the turn_id of the moment",
    "type": "strength" | "weakness",
    "label": "short label (max 6 words)",
    "explanation": "what the rep did and why it matters (2-3 sentences)",
    "coaching_tip": "what the rep should have said or done instead (1-2 sentences, only for weakness type)"
  }}
]
""".strip()

        result = self._call_manager_ai_json(
            system_prompt=(
                f"{coaching_system_prefix}\n\n"
                "You are a precise transcript coach. Return only valid JSON."
            ),
            user_prompt=prompt,
            max_tokens=1000,
            task="session_annotations",
            validator=lambda payload: [
                SessionAnnotation.model_validate(item).model_dump(mode="json")
                for item in payload
            ]
            if isinstance(payload, list)
            else (_ for _ in ()).throw(ValueError("annotations_payload_invalid")),
        )
        raw_items = result.payload

        turn_index_by_id = {turn.id: turn.turn_index for turn in turns}
        seen_turn_ids: set[str] = set()
        annotations: list[SessionAnnotation] = []
        for item in raw_items:
            annotation = SessionAnnotation.model_validate(item)
            if annotation.turn_id not in turn_index_by_id or annotation.turn_id in seen_turn_ids:
                continue
            seen_turn_ids.add(annotation.turn_id)
            annotations.append(annotation)

        annotations.sort(key=lambda item: turn_index_by_id[item.turn_id])
        generated_at = datetime.now(timezone.utc).isoformat()
        response = SessionAnnotationsResponse(
            session_id=session_id,
            generated_at=generated_at,
            annotations=annotations,
            ai_meta=self._ai_meta_from_result(result, generated_at=generated_at),
        )
        self.session_annotations_cache.set_json(cache_key, response.model_dump(mode="json"))
        return response

    def generate_team_coaching_summary(
        self,
        *,
        manager: User,
        period_days: int,
        coaching_analytics: dict[str, Any],
    ) -> TeamCoachingSummaryResponse:
        db = object_session(manager)
        coaching_system_prefix = (
            self._get_coaching_system_prefix(db, manager.org_id)
            if db is not None
            else DEFAULT_COACHING_SYSTEM_PREFIX
        )
        summary = coaching_analytics.get("summary", {}) if isinstance(coaching_analytics, dict) else {}
        weakness_items = coaching_analytics.get("weakness_tag_uplift", []) if isinstance(coaching_analytics, dict) else []
        uplift_items = coaching_analytics.get("coaching_uplift", []) if isinstance(coaching_analytics, dict) else []
        calibration_items = coaching_analytics.get("manager_calibration", []) if isinstance(coaching_analytics, dict) else []
        recent_notes = coaching_analytics.get("recent_notes", []) if isinstance(coaching_analytics, dict) else []
        retry_items = coaching_analytics.get("retry_impact", []) if isinstance(coaching_analytics, dict) else []

        top_weaknesses = [
            {
                "tag": item.get("tag"),
                "delta": item.get("delta"),
                "sample_size": item.get("sample_size"),
            }
            for item in weakness_items[:4]
            if isinstance(item, dict)
        ]
        top_uplifts = [
            {
                "rep_name": item.get("rep_name"),
                "delta": item.get("delta"),
                "outcome": item.get("outcome"),
                "visible_to_rep": item.get("visible_to_rep"),
            }
            for item in uplift_items[:3]
            if isinstance(item, dict)
        ]
        highest_drift = sorted(
            [
                {
                    "reviewer_name": item.get("reviewer_name"),
                    "average_override_delta": item.get("average_override_delta"),
                    "absolute_average_delta": item.get("absolute_average_delta"),
                }
                for item in calibration_items
                if isinstance(item, dict)
            ],
            key=lambda item: abs(float(item.get("absolute_average_delta") or 0.0)),
            reverse=True,
        )[:2]
        recent_note_previews = [
            {
                "rep_name": item.get("rep_name"),
                "weakness_tags": item.get("weakness_tags"),
                "note": item.get("note"),
                "delta": item.get("delta"),
            }
            for item in recent_notes[:3]
            if isinstance(item, dict)
        ]

        prompt = f"""
You are an expert D2D sales coaching strategist summarizing a manager's coaching patterns.

Manager data:
- Manager: {manager.name}
- Period: {period_days} days
- Coaching notes: {summary.get('coaching_note_count', 0)}
- Reviews: {summary.get('review_count', 0)}
- Override rate: {round(float(summary.get('override_rate', 0.0)) * 100, 1)}%
- Avg override delta: {summary.get('average_override_delta')}
- Retry uplift avg: {summary.get('retry_uplift_avg')}
- Coached retry uplift avg: {summary.get('coached_retry_uplift_avg')}
- Intervention improved rate: {summary.get('intervention_improved_rate')}
- Calibration drift score: {summary.get('calibration_drift_score')}
- Top weakness trends: {json.dumps(top_weaknesses, default=str)}
- Strongest coaching uplifts: {json.dumps(top_uplifts, default=str)}
- Highest calibration drift: {json.dumps(highest_drift, default=str)}
- Recent coaching notes: {json.dumps(recent_note_previews, default=str)}
- Retry samples: {json.dumps(retry_items[:3], default=str)}

Return JSON:
{{
  "summary": "Exactly 3 sentences. Be specific, managerial, and action-oriented."
}}
""".strip()

        result = self._call_manager_ai_json(
            system_prompt=(
                f"{coaching_system_prefix}\n\n"
                "You are a precise coaching strategist. Return only valid JSON."
            ),
            user_prompt=prompt,
            max_tokens=320,
            task="team_coaching_summary",
            validator=TeamCoachingSummaryContent.model_validate,
        )
        content = result.payload
        summary_text = _trim_to_three_sentences(content.summary)
        if _sentence_count(summary_text) > 3:
            summary_text = _trim_to_three_sentences(summary_text)

        data_summary = {
            "period_days": period_days,
            "summary": summary,
            "top_weakness_trends": top_weaknesses,
            "strongest_uplifts": top_uplifts,
            "highest_calibration_drift": highest_drift,
            "recent_note_previews": recent_note_previews,
        }
        generated_at = datetime.now(timezone.utc).isoformat()
        return TeamCoachingSummaryResponse(
            manager_id=manager.id,
            period_days=period_days,
            generated_at=generated_at,
            summary=summary_text,
            data_summary=data_summary,
            ai_meta=self._ai_meta_from_result(result, generated_at=generated_at),
        )

    def _call_claude_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        model: str | None = None,
    ) -> Any:
        del model
        return self._call_manager_ai_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            task="legacy_manager_ai",
        ).payload
