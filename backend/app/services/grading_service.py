from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import SessionStatus
from app.schemas.scorecard import StructuredScorecardPayloadV2
from app.services.analytics_refresh_service import AnalyticsRefreshService

CATEGORY_KEYS = [
    "opening",
    "pitch_delivery",
    "objection_handling",
    "closing_technique",
    "professionalism",
]
CATEGORY_WEIGHTS = {
    "opening": 0.15,
    "pitch_delivery": 0.25,
    "objection_handling": 0.30,
    "closing_technique": 0.20,
    "professionalism": 0.10,
}
CATEGORY_STAGE_HINTS = {
    "opening": {"door_knock", "opening", "initial_pitch"},
    "pitch_delivery": {"initial_pitch", "pitch", "value_prop"},
    "objection_handling": {"objection_handling"},
    "closing_technique": {"close_attempt", "closing"},
    "professionalism": set(),
}
CLOSE_HINTS = ("today", "schedule", "next step", "book", "move forward", "sign up", "get started")


def _clip_text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _score_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("score")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


class GradingPromptBuilder:
    @classmethod
    def template_blueprint(cls) -> str:
        return (
            "Return valid JSON only.\n"
            "Use category_scores with keys opening, pitch_delivery, objection_handling, closing_technique, professionalism.\n"
            "Each category must contain score, confidence, rationale_summary, rationale_detail, evidence_turn_ids, "
            "behavioral_signals, and improvement_target.\n"
            "All evidence_turn_ids must refer to turn ids that appear in the transcript.\n"
            "Compute weighted overall_score using 15/25/30/20/10 weights.\n"
            "Provide 2-4 highlights using type strong|improve, plus a plain-English second-person ai_summary.\n"
            "Set evidence_quality to strong|moderate|weak and session_complexity to 1-5."
        )

    def build(self, turns: list[Any], *, prompt_template: str | None = None) -> str:
        transcript_rows = [
            f'{turn.turn_index}. ({turn.id}) [{turn.speaker.value}/{turn.stage}] "{turn.text}"'
            for turn in turns
        ]
        transcript_text = "\n".join(transcript_rows) or "No transcript turns captured."
        schema = StructuredScorecardPayloadV2.model_json_schema()
        instructions = prompt_template or self.template_blueprint()
        return (
            "You are grading a door-to-door sales training session.\n"
            "Be evidence-based, strict, and specific.\n"
            f"{instructions}\n"
            "The ai_summary must be plain English, written directly to the rep in second person.\n"
            "Highlights must contain 2 to 4 items with type 'strong' or 'improve'.\n"
            "Use this JSON schema shape:\n"
            f"{json.dumps(schema, ensure_ascii=True)}\n"
            "Transcript:\n"
            f"{transcript_text}"
        )


class GradingService:
    """Async grading service with prompt version audit trail and deterministic fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.prompt_builder = GradingPromptBuilder()
        self.analytics_refresh_service = AnalyticsRefreshService()
        self._active_prompt_version_id: str | None = None

    async def grade_session(self, db: Session, session_id: str) -> Scorecard:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        if session is None:
            raise ValueError("session not found")

        prompt_version = self._ensure_active_prompt_version(db)
        self._active_prompt_version_id = prompt_version.id

        grading_run = GradingRun(
            session_id=session_id,
            prompt_version_id=prompt_version.id,
            model_name=self.settings.openai_model,
            model_latency_ms=0,
            status="running",
            confidence_score=0.0,
            started_at=datetime.now(timezone.utc),
        )
        db.add(grading_run)
        db.flush()

        llm_result = await self._grade_with_llm(
            session=session,
            prompt_template=prompt_version.content,
        )
        grading = llm_result["grading"]
        category_scores = grading["category_scores"]
        overall = grading["overall_score"]
        weakness_tags = grading["weakness_tags"]
        evidence = grading["evidence_turn_ids"]
        highlights = grading["highlights"]
        ai_summary = grading["ai_summary"]

        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        if scorecard is None:
            scorecard = Scorecard(
                session_id=session_id,
                overall_score=overall,
                scorecard_schema_version="v2",
                category_scores=category_scores,
                highlights=highlights,
                ai_summary=ai_summary,
                evidence_turn_ids=[e for e in evidence if e],
                weakness_tags=weakness_tags,
            )
            db.add(scorecard)
        else:
            scorecard.overall_score = overall
            scorecard.scorecard_schema_version = "v2"
            scorecard.category_scores = category_scores
            scorecard.highlights = highlights
            scorecard.ai_summary = ai_summary
            scorecard.evidence_turn_ids = [e for e in evidence if e]
            scorecard.weakness_tags = weakness_tags

        session.status = SessionStatus.GRADED
        session.ended_at = session.ended_at or datetime.now(timezone.utc)

        db.flush()
        grading_run.scorecard_id = scorecard.id
        grading_run.status = llm_result["status"]
        grading_run.model_latency_ms = llm_result["model_latency_ms"]
        grading_run.input_token_count = llm_result["input_token_count"]
        grading_run.output_token_count = llm_result["output_token_count"]
        grading_run.raw_llm_response = llm_result["raw_llm_response"]
        grading_run.parse_error = llm_result["parse_error"]
        grading_run.overall_score = overall
        grading_run.confidence_score = float(grading.get("confidence_score") or 0.0)
        grading_run.completed_at = datetime.now(timezone.utc)

        self.analytics_refresh_service.refresh_session(db, session_id=session_id)
        db.commit()
        db.refresh(scorecard)
        return scorecard

    def _get_active_prompt_version(self, db: Session) -> PromptVersion | None:
        return db.scalar(
            select(PromptVersion)
            .where(PromptVersion.prompt_type == "grading_v2")
            .where(PromptVersion.active.is_(True))
            .order_by(PromptVersion.created_at.desc())
        )

    def _ensure_active_prompt_version(self, db: Session) -> PromptVersion:
        row = self._get_active_prompt_version(db)
        if row is not None:
            return row

        row = db.scalar(
            select(PromptVersion).where(
                PromptVersion.prompt_type == "grading_v2",
                PromptVersion.version == "1.0.0",
            )
        )
        if row is None:
            row = PromptVersion(
                prompt_type="grading_v2",
                version="1.0.0",
                content=GradingPromptBuilder.template_blueprint(),
                active=True,
            )
            db.add(row)
            db.flush()
        else:
            row.content = GradingPromptBuilder.template_blueprint()
            row.active = True

        for existing in db.scalars(select(PromptVersion).where(PromptVersion.prompt_type == "grading_v2")).all():
            existing.active = existing.id == row.id
        db.flush()
        return row

    async def _grade_with_llm(
        self,
        *,
        session: DrillSession,
        prompt_template: str,
    ) -> dict[str, Any]:
        turns = list(session.turns)
        rep_turns = [t for t in turns if t.speaker.value == "rep"]
        ai_turns = [t for t in turns if t.speaker.value == "ai"]
        fallback = self._grade_with_fallback(session=session, rep_turns=rep_turns, ai_turns=ai_turns)

        if not self.settings.openai_api_key or os.getenv("PYTEST_CURRENT_TEST"):
            return {
                "status": "fallback_used",
                "grading": fallback,
                "raw_llm_response": None,
                "parse_error": "llm disabled for local/test execution",
                "input_token_count": None,
                "output_token_count": None,
                "model_latency_ms": 0,
            }

        prompt = self.prompt_builder.build(turns, prompt_template=prompt_template)
        started = perf_counter()
        url = f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.openai_model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "You are a strict D2D sales manager grading rep performance with exact evidence.",
                },
                {"role": "user", "content": prompt},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            return {
                "status": "llm_error",
                "grading": fallback,
                "raw_llm_response": None,
                "parse_error": _clip_text(exc, limit=1000),
                "input_token_count": None,
                "output_token_count": None,
                "model_latency_ms": int((perf_counter() - started) * 1000),
            }

        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        raw_response = content if isinstance(content, str) else json.dumps(content, ensure_ascii=True)
        usage = body.get("usage", {}) if isinstance(body, dict) else {}

        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            if not isinstance(parsed, dict):
                raise ValueError("llm returned non-object payload")
            normalized = self._normalize_grading(parsed, session=session)
            status = "success"
            parse_error = None
        except Exception as exc:
            normalized = fallback
            status = "parse_error"
            parse_error = _clip_text(exc, limit=1000)

        return {
            "status": status,
            "grading": normalized,
            "raw_llm_response": raw_response[:12000] if raw_response else None,
            "parse_error": parse_error,
            "input_token_count": usage.get("prompt_tokens"),
            "output_token_count": usage.get("completion_tokens"),
            "model_latency_ms": int((perf_counter() - started) * 1000),
        }

    def _grade_with_fallback(
        self,
        *,
        session: DrillSession,
        rep_turns: list[Any],
        ai_turns: list[Any],
    ) -> dict[str, Any]:
        depth = max(1, len(rep_turns))
        opening = min(10.0, 6.0 + depth * 0.3)
        pitch = min(10.0, 5.5 + depth * 0.35)
        objections = min(10.0, 5.0 + len([t for t in rep_turns if "price" in t.text.lower()]) * 1.0)
        closing = min(
            10.0,
            5.0 + len([t for t in rep_turns if "schedule" in t.text.lower() or "today" in t.text.lower()]) * 1.2,
        )
        professionalism = min(10.0, 6.5 + (0.2 if len(ai_turns) > 0 else 0.0))

        fallback_scores = {
            "opening": round(opening, 1),
            "pitch_delivery": round(pitch, 1),
            "objection_handling": round(objections, 1),
            "closing_technique": round(closing, 1),
            "professionalism": round(professionalism, 1),
        }

        category_scores: dict[str, dict[str, Any]] = {}
        for key in CATEGORY_KEYS:
            evidence_turn_ids = self._fallback_evidence_turn_ids(rep_turns=rep_turns, category_key=key)
            behavioral_signals = self._collect_behavioral_signals(turns=rep_turns, evidence_turn_ids=evidence_turn_ids)
            score = fallback_scores[key]
            category_scores[key] = {
                "score": score,
                "confidence": 0.0,
                "rationale_summary": self._fallback_rationale_summary(key, score=score),
                "rationale_detail": self._fallback_rationale_detail(key, score=score),
                "evidence_turn_ids": evidence_turn_ids,
                "behavioral_signals": behavioral_signals,
                "improvement_target": self._fallback_improvement_target(key, score=score),
            }

        overall = self._calculate_weighted_overall(category_scores)
        evidence_turn_ids = self._aggregate_evidence_turn_ids(category_scores)
        weakness_tags = [key for key in CATEGORY_KEYS if _score_value(category_scores.get(key)) is not None and float(_score_value(category_scores.get(key)) or 0.0) < 7.0]
        if not weakness_tags and overall < 8.0:
            weakness_tags = ["consistency"]

        highlights = [
            {
                "type": "strong",
                "note": "You kept the conversation moving and created enough structure to stay in the drill.",
                "turn_id": evidence_turn_ids[0] if evidence_turn_ids else None,
            },
            {
                "type": "improve",
                "note": "Ask for a direct next step sooner when interest appears.",
                "turn_id": evidence_turn_ids[-1] if evidence_turn_ids else None,
            },
        ]

        base = {
            "overall_score": overall,
            "category_scores": category_scores,
            "highlights": highlights,
            "ai_summary": "You kept control of the drill, but you need clearer objection reframing and a more direct close.",
            "evidence_turn_ids": evidence_turn_ids,
            "weakness_tags": weakness_tags,
            "evidence_quality": "weak",
            "session_complexity": self._compute_session_complexity(session),
        }
        confidence = self.compute_confidence(session, base)
        for key in CATEGORY_KEYS:
            category_scores[key]["confidence"] = self._compute_category_confidence(
                session=session,
                category_key=key,
                evidence_turn_ids=category_scores[key]["evidence_turn_ids"],
                overall_confidence=confidence,
            )
        base["confidence_score"] = confidence
        base["evidence_quality"] = self._evidence_quality(confidence)
        return base

    def _normalize_grading(self, payload: dict[str, Any], *, session: DrillSession) -> dict[str, Any]:
        turns = list(session.turns)
        valid_turn_ids = {turn.id for turn in turns}
        fallback = self._grade_with_fallback(
            session=session,
            rep_turns=[turn for turn in turns if turn.speaker.value == "rep"],
            ai_turns=[turn for turn in turns if turn.speaker.value == "ai"],
        )

        raw_scores = payload.get("category_scores", {})
        category_scores: dict[str, dict[str, Any]] = {}
        for key in CATEGORY_KEYS:
            source = raw_scores.get(key) if isinstance(raw_scores, dict) else {}
            source = source if isinstance(source, dict) else {}
            fallback_category = fallback["category_scores"][key]
            score = _score_value(source)
            if score is None:
                score = float(fallback_category["score"])
            evidence_turn_ids = [
                turn_id
                for turn_id in source.get("evidence_turn_ids", [])
                if isinstance(turn_id, str) and turn_id in valid_turn_ids
            ]
            if not evidence_turn_ids:
                evidence_turn_ids = list(fallback_category["evidence_turn_ids"])

            behavioral_signals = [
                _clip_text(item, limit=64)
                for item in source.get("behavioral_signals", [])
                if isinstance(item, str) and str(item).strip()
            ]
            if not behavioral_signals:
                behavioral_signals = self._collect_behavioral_signals(turns=turns, evidence_turn_ids=evidence_turn_ids)

            rationale_summary = _clip_text(
                source.get("rationale_summary") or source.get("rationale"),
                limit=80,
            ) or fallback_category["rationale_summary"]
            rationale_detail = _clip_text(
                source.get("rationale_detail") or source.get("rationale"),
                limit=400,
            ) or fallback_category["rationale_detail"]
            improvement_target = _clip_text(source.get("improvement_target"), limit=60) or fallback_category["improvement_target"]

            category_scores[key] = {
                "score": round(max(0.0, min(10.0, float(score))), 1),
                "confidence": 0.0,
                "rationale_summary": rationale_summary,
                "rationale_detail": rationale_detail,
                "evidence_turn_ids": evidence_turn_ids,
                "behavioral_signals": list(dict.fromkeys(behavioral_signals))[:6],
                "improvement_target": improvement_target or None,
            }

        overall = payload.get("overall_score")
        try:
            overall_score = round(max(0.0, min(10.0, float(overall))), 2)
        except Exception:
            overall_score = self._calculate_weighted_overall(category_scores)

        raw_highlights = payload.get("highlights", [])
        highlights = []
        if isinstance(raw_highlights, list):
            for item in raw_highlights[:4]:
                if not isinstance(item, dict):
                    continue
                note = _clip_text(item.get("note"), limit=240)
                if not note:
                    continue
                turn_id = item.get("turn_id")
                if turn_id not in valid_turn_ids:
                    turn_id = None
                highlight_type = str(item.get("type", "improve")).strip() or "improve"
                if highlight_type not in {"strong", "improve"}:
                    highlight_type = "improve"
                highlights.append({"type": highlight_type, "note": note, "turn_id": turn_id})
        if len(highlights) < 2:
            highlights = fallback["highlights"]

        evidence_turn_ids = self._aggregate_evidence_turn_ids(category_scores)
        top_level_evidence = payload.get("evidence_turn_ids", [])
        if isinstance(top_level_evidence, list):
            evidence_turn_ids = list(
                dict.fromkeys(
                    evidence_turn_ids
                    + [turn_id for turn_id in top_level_evidence if isinstance(turn_id, str) and turn_id in valid_turn_ids]
                )
            )
        if not evidence_turn_ids:
            evidence_turn_ids = fallback["evidence_turn_ids"]

        ai_summary = _clip_text(payload.get("ai_summary"), limit=400) or fallback["ai_summary"]
        weakness_tags = [
            _clip_text(tag, limit=60)
            for tag in payload.get("weakness_tags", [])
            if isinstance(tag, str) and str(tag).strip()
        ]
        if not weakness_tags:
            weakness_tags = [
                key
                for key, value in category_scores.items()
                if float(value["score"]) < 7.0
            ] or list(fallback["weakness_tags"])

        normalized = {
            "overall_score": overall_score,
            "category_scores": category_scores,
            "highlights": highlights,
            "ai_summary": ai_summary,
            "evidence_turn_ids": evidence_turn_ids,
            "weakness_tags": weakness_tags,
            "evidence_quality": payload.get("evidence_quality"),
            "session_complexity": payload.get("session_complexity"),
        }
        confidence = self.compute_confidence(session, normalized)
        for key in CATEGORY_KEYS:
            category_scores[key]["confidence"] = self._compute_category_confidence(
                session=session,
                category_key=key,
                evidence_turn_ids=category_scores[key]["evidence_turn_ids"],
                overall_confidence=confidence,
            )
        normalized["confidence_score"] = confidence
        normalized["evidence_quality"] = normalized["evidence_quality"] if normalized["evidence_quality"] in {"strong", "moderate", "weak"} else self._evidence_quality(confidence)

        session_complexity = normalized["session_complexity"]
        if not isinstance(session_complexity, int) or not 1 <= session_complexity <= 5:
            normalized["session_complexity"] = self._compute_session_complexity(session)
        return normalized

    def compute_confidence(self, session: DrillSession, grading: dict[str, Any]) -> float:
        rep_turns = [t for t in session.turns if t.speaker.value == "rep"]
        evidence_ids = set(grading.get("evidence_turn_ids", []))
        turn_factor = min(1.0, len(rep_turns) / 10.0)
        evidence_density = min(1.0, len(evidence_ids) / max(1, len(rep_turns)))

        objection_turns = [
            turn
            for turn in session.turns
            if turn.stage == "objection_handling" or bool(turn.objection_tags)
        ]
        objection_evidence = len([turn for turn in objection_turns if turn.id in evidence_ids])
        objection_coverage = objection_evidence / len(objection_turns) if objection_turns else 1.0

        reached_close = any(
            turn.stage == "close_attempt" or any(hint in turn.text.lower() for hint in CLOSE_HINTS)
            for turn in rep_turns
        )
        completion_factor = 1.0 if reached_close else 0.35

        present = len(
            [
                key
                for key, value in (grading.get("category_scores") or {}).items()
                if key in CATEGORY_KEYS and isinstance(value, dict) and 0.0 <= float(value.get("score", -1)) <= 10.0
            ]
        )
        parse_quality = present / float(len(CATEGORY_KEYS))
        confidence = min(
            1.0,
            (turn_factor * 0.25)
            + (evidence_density * 0.25)
            + (objection_coverage * 0.20)
            + (completion_factor * 0.15)
            + (parse_quality * 0.15),
        )
        return round(confidence, 3)

    def _compute_category_confidence(
        self,
        *,
        session: DrillSession,
        category_key: str,
        evidence_turn_ids: list[str],
        overall_confidence: float,
    ) -> float:
        rep_turns = [turn for turn in session.turns if turn.speaker.value == "rep"]
        evidence_density = min(1.0, len(evidence_turn_ids) / max(1, len(rep_turns)))
        stage_hints = CATEGORY_STAGE_HINTS.get(category_key, set())
        stage_matches = len(
            [
                turn
                for turn in session.turns
                if turn.id in set(evidence_turn_ids) and (not stage_hints or turn.stage in stage_hints)
            ]
        )
        stage_factor = 1.0 if stage_matches else (0.5 if evidence_turn_ids else 0.0)
        confidence = min(1.0, (overall_confidence * 0.6) + (evidence_density * 0.25) + (stage_factor * 0.15))
        return round(confidence, 3)

    def _compute_session_complexity(self, session: DrillSession) -> int:
        turn_count = len(session.turns)
        objection_depth = len(
            [
                turn
                for turn in session.turns
                if turn.stage == "objection_handling" or bool(turn.objection_tags)
            ]
        )
        raw = 1 + min(2, turn_count // 6) + min(2, objection_depth // 2)
        return max(1, min(5, raw))

    def _evidence_quality(self, confidence: float) -> str:
        if confidence >= 0.75:
            return "strong"
        if confidence >= 0.45:
            return "moderate"
        return "weak"

    def _aggregate_evidence_turn_ids(self, category_scores: dict[str, Any]) -> list[str]:
        evidence_turn_ids: list[str] = []
        for key in CATEGORY_KEYS:
            category = category_scores.get(key)
            if not isinstance(category, dict):
                continue
            evidence_turn_ids.extend(
                turn_id
                for turn_id in category.get("evidence_turn_ids", [])
                if isinstance(turn_id, str) and turn_id
            )
        return list(dict.fromkeys(evidence_turn_ids))

    def _fallback_evidence_turn_ids(self, *, rep_turns: list[Any], category_key: str) -> list[str]:
        stage_hints = CATEGORY_STAGE_HINTS.get(category_key, set())
        staged = [turn.id for turn in rep_turns if not stage_hints or turn.stage in stage_hints]
        if category_key == "objection_handling":
            staged = [
                turn.id
                for turn in rep_turns
                if turn.stage == "objection_handling"
                or "price" in turn.text.lower()
                or bool(turn.objection_tags)
            ] or staged
        if category_key == "closing_technique":
            staged = [
                turn.id
                for turn in rep_turns
                if turn.stage == "close_attempt" or any(hint in turn.text.lower() for hint in CLOSE_HINTS)
            ] or staged
        if not staged and rep_turns:
            staged = [rep_turns[0].id]
        return list(dict.fromkeys(staged[:3]))

    def _collect_behavioral_signals(self, *, turns: list[Any], evidence_turn_ids: list[str]) -> list[str]:
        signal_values: list[str] = []
        for turn in turns:
            if turn.id not in set(evidence_turn_ids):
                continue
            for values in (turn.behavioral_signals or [], turn.mb_behaviors or []):
                if isinstance(values, list):
                    signal_values.extend(
                        _clip_text(item, limit=64)
                        for item in values
                        if isinstance(item, str) and str(item).strip()
                    )
        return list(dict.fromkeys(signal_values))[:6]

    def _fallback_rationale_summary(self, category_key: str, *, score: float) -> str:
        templates = {
            "opening": "Initial approach created enough engagement.",
            "pitch_delivery": "Value pitch was understandable but not sharp enough.",
            "objection_handling": "Objection response needed stronger reframing.",
            "closing_technique": "Close attempt was present but not decisive.",
            "professionalism": "Tone stayed professional throughout the exchange.",
        }
        summary = templates.get(category_key, "Performance showed partial evidence.")
        if score >= 8.0:
            return summary.replace("but not sharp enough", "and clearly structured")
        return summary[:80]

    def _fallback_rationale_detail(self, category_key: str, *, score: float) -> str:
        label = category_key.replace("_", " ")
        if score >= 8.0:
            return f"Your {label} showed clear evidence of control and consistency in the recorded turns."
        if score >= 6.5:
            return f"Your {label} was serviceable, but the available evidence still left room for a clearer, more complete rep response."
        return f"Your {label} lacked enough strong evidence to support a higher grade in this session."

    def _fallback_improvement_target(self, category_key: str, *, score: float) -> str | None:
        if score >= 8.0:
            return None
        targets = {
            "opening": "Lead with a tighter reason for stopping",
            "pitch_delivery": "State value in one crisp sentence",
            "objection_handling": "Acknowledge then reframe the objection",
            "closing_technique": "Ask directly for the next step",
            "professionalism": "Slow down and keep the tone steady",
        }
        return targets.get(category_key)

    def _calculate_weighted_overall(self, category_scores: dict[str, Any]) -> float:
        total = sum(float(_score_value(category_scores.get(key)) or 0.0) * weight for key, weight in CATEGORY_WEIGHTS.items())
        return round(max(0.0, min(10.0, total)), 2)
