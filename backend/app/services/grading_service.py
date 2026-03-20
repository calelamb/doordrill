from __future__ import annotations

from dataclasses import asdict
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
from app.models.scenario import Scenario
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact
from app.models.types import SessionStatus
from app.schemas.scorecard import StructuredScorecardPayloadV2
from app.services.analytics_refresh_service import AnalyticsRefreshService
from app.services.document_retrieval_service import DocumentRetrievalService
from app.services.inflection_point_service import InflectionPointService
from app.services.grading_technique_service import GradingTechniqueService
from app.services.prompt_version_resolver import prompt_version_resolver
from app.services.turn_enrichment_service import ReconstructedTimeline, TurnEnrichmentService

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
DIFFICULTY_LABEL = {1: "easy", 2: "moderate", 3: "challenging", 4: "hard", 5: "very hard"}
OPENING_SIGNAL_LABELS = {
    "builds_rapport": "strong opener",
    "mentions_social_proof": "strong opener",
    "explains_value": "neutral opener",
    "neutral_delivery": "weak opener",
    "pushes_close": "damaging opener",
    "dismisses_concern": "damaging opener",
}
POSITIVE_RECOVERY_EMOTIONS = {"curious", "interested"}
MAX_TRANSCRIPT_TURNS_FOR_GRADING = 20
TECHNIQUE_EVAL_ARTIFACT_TYPE = "grading_technique_evaluation"
SIGNAL_SCORE_MAP: dict[str, dict[str, float]] = {
    "opening": {
        "builds_rapport": 1.5,
        "mentions_social_proof": 1.0,
        "neutral_delivery": -0.5,
        "pushes_close": -2.5,
        "dismisses_concern": -2.0,
    },
    "pitch_delivery": {
        "explains_value": 1.5,
        "personalizes_pitch": 1.0,
        "provides_proof": 0.8,
        "neutral_delivery": -0.5,
        "pushes_close": -1.0,
    },
    "objection_handling": {
        "acknowledges_concern": 2.0,
        "explains_value": 1.0,
        "reduces_pressure": 1.0,
        "provides_proof": 1.0,
        "ignores_objection": -2.5,
        "dismisses_concern": -2.5,
        "high_difficulty_backfire": -1.5,
    },
    "closing_technique": {
        "invites_dialogue": 1.0,
        "reduces_pressure": 0.5,
        "pushes_close": -1.5,
    },
    "professionalism": {
        "builds_rapport": 0.5,
        "personalizes_pitch": 0.5,
        "acknowledges_concern": 0.5,
        "dismisses_concern": -1.5,
        "pushes_close": -1.0,
    },
}
WEAKNESS_TAG_SIGNAL_TRIGGERS: dict[str, list[str]] = {
    "objection_handling": ["ignores_objection", "dismisses_concern", "high_difficulty_backfire"],
    "closing_technique": ["pushes_close"],
    "opening": ["neutral_delivery", "pushes_close"],
    "pitch_delivery": ["neutral_delivery"],
    "professionalism": ["dismisses_concern", "pushes_close"],
}
WEAKNESS_TAG_SIGNAL_THRESHOLD = 2
CATEGORY_RUBRICS = {
    "opening": {
        "description": "How the rep introduced themselves and established the reason for the visit.",
        "anchors": {
            "9-10": "Clear name + company + specific reason for visit. Acknowledged the homeowner's time. Felt natural, not scripted. Homeowner stayed engaged.",
            "7-8": "Introduced themselves but reason for visit was vague. Rapport attempt was present but slightly robotic.",
            "5-6": "Skipped intro or gave a generic opener ('I'm in the neighborhood'). No rapport attempt.",
            "1-4": "No introduction, jumped straight to pitch or close. Created immediate resistance.",
        },
    },
    "pitch_delivery": {
        "description": "How the rep explained the product/service and made the value case.",
        "anchors": {
            "9-10": "One clear benefit tied to this homeowner's specific situation. Used concrete details (price range, process). No filler.",
            "7-8": "Value was communicated but generic. Could apply to any homeowner. Not tailored.",
            "5-6": "Pitch was present but buried in features. Homeowner had to ask what it actually costs or does.",
            "1-4": "No pitch, or pitch was confusing or irrelevant. Homeowner showed no comprehension of the offer.",
        },
    },
    "objection_handling": {
        "description": "How the rep responded when the homeowner raised concerns or resistance.",
        "anchors": {
            "9-10": "Acknowledged the specific objection, reframed it with evidence, and reduced friction. Homeowner moved toward curious or interested.",
            "7-8": "Addressed the objection but reframe was generic. Homeowner softened slightly but objection was not fully resolved.",
            "5-6": "Rep acknowledged the objection but did not resolve it. Changed subject or repeated the original claim.",
            "1-4": "Rep ignored, dismissed, or talked over the objection. Homeowner escalated or ended the conversation.",
        },
    },
    "closing_technique": {
        "description": "How the rep asked for the next step or commitment.",
        "anchors": {
            "9-10": "Asked for a specific, low-friction next step at the right moment. Framing was confident but not pushy. Homeowner agreed or gave a qualified response.",
            "7-8": "Close attempt was present but too early or too vague ('Does that sound good?'). Homeowner deflected.",
            "5-6": "Rep hinted at wanting to move forward but never actually asked. Or asked too many times.",
            "1-4": "No close attempt, or used hard-pressure close ('Sign today', 'Right now'). Homeowner rejected immediately.",
        },
    },
    "professionalism": {
        "description": "Overall tone, pacing, and conduct throughout the session.",
        "anchors": {
            "9-10": "Steady throughout. Never flustered. Handled resistance with composure. Pacing felt natural.",
            "7-8": "Generally professional but one or two moments of unnecessary filler, rushing, or breaking character.",
            "5-6": "Noticeable tone issues - too eager, defensive, or apologetic. Affected the homeowner's trust.",
            "1-4": "Unprofessional conduct: interrupting, dismissing concerns, getting frustrated, or asking for hints.",
        },
    },
}
SCORE_CALIBRATION_INSTRUCTION = (
    "SCORE CALIBRATION: Use the full 0-10 range. Do not default to 6-7 for everything.\n"
    "  - 9-10: Genuinely exceptional. Evidence is clear, specific, and impactful.\n"
    "  - 7-8:  Competent. The rep did this correctly but left clear room for improvement.\n"
    "  - 5-6:  Below average. Present but not effective. The homeowner was not moved.\n"
    "  - 1-4:  Poor. Active mistakes that hurt the session.\n"
    "  - 0:    Absent. The rep did not attempt this at all.\n"
    "If all five of your category scores land between 6.0 and 7.5, recalibrate - "
    "that range should only be used when every category is genuinely middle-of-the-road.\n"
)
AI_SUMMARY_INSTRUCTION = (
    "ai_summary format (max 700 chars, second person, plain English, no jargon):\n"
    "  Sentence 1: What the rep did well - specific, with evidence ('You opened with a neighbor reference that worked').\n"
    "  Sentence 2: The moment things shifted - the specific turn where the conversation changed and why.\n"
    "  Sentence 3: The one concrete fix - not a category name, a specific behavior ('Next time, acknowledge the price objection before explaining value').\n"
    "Do not start with 'Overall' or 'In this session'. Start with what the rep did.\n"
)


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


def _has_meaningful_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    meaningful_chars = [char for char in text if char.isalnum()]
    return len(meaningful_chars) >= 3


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _opening_quality_label(first_turn_signals: list[str]) -> str | None:
    labels = [OPENING_SIGNAL_LABELS[signal] for signal in first_turn_signals if signal in OPENING_SIGNAL_LABELS]
    if not labels:
        return None
    if "damaging opener" in labels:
        return "damaging opener"
    if "weak opener" in labels:
        return "weak opener"
    if "strong opener" in labels:
        return "strong opener"
    return "neutral opener"


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
            "Set evidence_quality to strong|moderate|weak and session_complexity to 1-5.\n"
            f"{SCORE_CALIBRATION_INSTRUCTION}"
        )

    def build(
        self,
        turns: list[Any],
        *,
        prompt_template: str | None = None,
        retrieved_context: str | None = None,
        technique_evaluation: dict[str, Any] | None = None,
        session_context: dict[str, Any] | None = None,
        first_turn_signals: list[str] | None = None,
        inflection_points: list[dict[str, Any]] | None = None,
    ) -> str:
        transcript_rows = [
            f'{turn.turn_index}. ({turn.id}) [{turn.speaker.value}/{turn.stage}] "{turn.text}"'
            for turn in turns
        ]
        transcript_text = "\n".join(transcript_rows) or "No transcript turns captured."
        schema = StructuredScorecardPayloadV2.model_json_schema()
        instructions = prompt_template or self.template_blueprint()
        parts = [
            "You are grading a door-to-door sales training session.",
            "Be evidence-based, strict, and specific.",
            instructions,
            retrieved_context or "",
            self._build_opening_modifier(first_turn_signals or []),
            self._build_session_context_block(session_context or {}),
            self._build_inflection_block(inflection_points or []),
            self._build_band_guard_block(technique_evaluation or {}),
            self._build_technique_check_block(technique_evaluation or {}),
            "The ai_summary must be plain English, written directly to the rep in second person.",
            AI_SUMMARY_INSTRUCTION,
            "Highlights must contain 2 to 4 items with type 'strong' or 'improve'.",
            self._build_rubric_block(),
            "Use this JSON schema shape:",
            json.dumps(schema, ensure_ascii=True),
            "Transcript:",
            transcript_text,
        ]
        return "\n".join(part for part in parts if part)

    def _build_rubric_block(self) -> str:
        lines = ["SCORING RUBRICS - use these to calibrate your scores. Do not compress scores into 6-7. Use the full 0-10 range.\n"]
        for key in CATEGORY_KEYS:
            rubric = CATEGORY_RUBRICS[key]
            lines.append(f"{key.upper()} - {rubric['description']}")
            for range_label, description in rubric["anchors"].items():
                lines.append(f"  {range_label}: {description}")
            lines.append("")
        return "\n".join(lines).strip()

    def _build_session_context_block(self, session_context: dict[str, Any]) -> str:
        if not session_context:
            return ""
        difficulty = int(session_context.get("difficulty", 1) or 1)
        trajectory = [str(item) for item in session_context.get("emotion_trajectory", []) if str(item).strip()]
        peak = int(session_context.get("peak_resistance", 0) or 0)
        resolved = [str(item) for item in session_context.get("objections_resolved", []) if str(item).strip()]
        turns = int(session_context.get("total_rep_turns", 0) or 0)
        label = DIFFICULTY_LABEL.get(difficulty, "unknown")
        trajectory_str = " -> ".join(trajectory) if trajectory else "unknown"
        resolved_str = ", ".join(resolved) if resolved else "none"
        return (
            "SESSION CONTEXT (use this to calibrate scores):\n"
            f"- Scenario difficulty: {difficulty}/5 ({label})\n"
            f"- Homeowner emotion trajectory: {trajectory_str}\n"
            f"- Peak resistance level reached: {peak}/5\n"
            f"- Objections resolved by rep: {resolved_str}\n"
            f"- Total rep turns: {turns}\n"
            "Adjust scores upward if the rep achieved good outcomes against high resistance. "
            "A rep who moved the homeowner from hostile to curious on difficulty 4 deserves more credit "
            "on objection_handling than a rep who got the same outcome on difficulty 1. "
            "Specifically: if peak_resistance >= 4, weight objection_handling evidence more heavily. "
            "If emotion_trajectory shows a recovery arc (hostile/annoyed -> neutral/curious), "
            "call that out as a highlight."
        )

    def _build_opening_modifier(self, first_turn_signals: list[str]) -> str:
        strongest = _opening_quality_label(first_turn_signals)
        if strongest is None:
            return ""
        body = f"OPENING QUALITY: {strongest} (signals: {', '.join(first_turn_signals)})."
        if strongest == "damaging opener":
            return (
                f"{body}\n"
                "The rep's opening created unnecessary resistance. "
                "When scoring objection_handling and closing_technique, note that the rep "
                "was working against resistance they created - factor that into your rationale."
            )
        if strongest == "strong opener":
            return (
                f"{body}\n"
                "The rep opened well, which likely made subsequent stages easier. "
                "Weight their early rapport positively in professionalism."
            )
        return body

    def _build_inflection_block(self, inflection_points: list[dict[str, Any]]) -> str:
        if not inflection_points:
            return ""
        lines = ["KEY MOMENTS IN THIS SESSION (use as evidence in your rationale):"]
        for point in inflection_points:
            label = str(point.get("coaching_label") or "").strip()
            note = str(point.get("coaching_note") or "").strip()
            direction = str(point.get("direction") or "").strip().upper() or "UNKNOWN"
            turn = point.get("turn_index", "?")
            lines.append(f"  - Turn {turn} [{direction}]: {label}. {note}".rstrip())
        lines.append(
            "Reference these moments in your highlights and rationale. "
            "If there is a clear 'Lost them here' moment, it should appear as an 'improve' highlight."
        )
        return "\n".join(lines)

    def _build_band_guard_block(self, technique_evaluation: dict[str, Any]) -> str:
        bands = technique_evaluation.get("bands")
        if not isinstance(bands, dict) or not bands:
            return ""
        lines = [
            "ALLOWED SCORE BANDS - you must keep each category score inside its allowed range.",
            "Do not score outside these ranges. If evidence is thin, stay near the center of the range.",
        ]
        for key in CATEGORY_KEYS:
            band = bands.get(key)
            if not isinstance(band, dict):
                continue
            floor = float(band.get("floor", 0.0) or 0.0)
            ceiling = float(band.get("ceiling", 10.0) or 10.0)
            anchor = float(band.get("anchor", (floor + ceiling) / 2.0) or 0.0)
            lines.append(f"- {key}: {floor:.1f} to {ceiling:.1f} (anchor {anchor:.1f})")
        return "\n".join(lines)

    def _build_technique_check_block(self, technique_evaluation: dict[str, Any]) -> str:
        checks = technique_evaluation.get("technique_checks")
        if not isinstance(checks, list) or not checks:
            return ""
        lines = ["PLAYBOOK TECHNIQUE CHECKS - ground your rationale in these observed call-quality patterns:"]
        for item in checks[:18]:
            if not isinstance(item, dict):
                continue
            label = _clip_text(item.get("label"), limit=90)
            category = _clip_text(item.get("category"), limit=32)
            status = _clip_text(item.get("status"), limit=24)
            evidence = ", ".join(
                turn_id for turn_id in item.get("evidence_turn_ids", []) if isinstance(turn_id, str) and turn_id
            )
            suffix = f" | evidence: {evidence}" if evidence else ""
            lines.append(f"- [{category}] {label}: {status}{suffix}")
        return "\n".join(lines)


class GradingService:
    """Async grading service with prompt version audit trail and deterministic fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.prompt_builder = GradingPromptBuilder()
        self.technique_service = GradingTechniqueService()
        self.analytics_refresh_service = AnalyticsRefreshService()
        self.document_retrieval_service = DocumentRetrievalService(settings=self.settings)
        self.turn_enrichment_service = TurnEnrichmentService()
        self.inflection_point_service = InflectionPointService()
        self.prompt_version_resolver = prompt_version_resolver
        self._active_prompt_version_id: str | None = None

    async def grade_session(self, db: Session, session_id: str) -> Scorecard:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        if session is None:
            raise ValueError("session not found")

        ordered_turns = self._ordered_turns(session.turns)
        timeline = self.turn_enrichment_service.build_timeline(db, session_id)
        session_context = self._build_session_context(db=db, session=session, turns=ordered_turns, timeline=timeline)
        first_turn_signals = self._first_turn_signals(turns=ordered_turns, timeline=timeline)
        inflection_points = self._resolve_inflection_points(db=db, session_id=session_id, timeline=timeline)
        org_id = session.rep.org_id if session.rep is not None else None
        prompt_version = self._select_prompt_version(db, session_id=session_id, org_id=org_id)
        self._active_prompt_version_id = prompt_version.id
        retrieved_context = self._build_effective_prompt_template(
            db,
            session=session,
            prompt_template=prompt_version.content,
            turns=ordered_turns,
            session_context=session_context,
        )

        grading_run = GradingRun(
            session_id=session_id,
            prompt_version_id=prompt_version.id,
            model_name=self.settings.grading_model,
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
            retrieved_context=retrieved_context,
            turns=ordered_turns,
            session_context=session_context,
            first_turn_signals=first_turn_signals,
            inflection_points=inflection_points,
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
        self._write_technique_artifact(
            db,
            session_id=session_id,
            grading=grading,
            technique_evaluation=llm_result.get("technique_evaluation"),
            grading_status=llm_result["status"],
            retry_requested=bool(llm_result.get("retry_requested")),
        )
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
        setattr(scorecard, "retry_requested", bool(llm_result.get("retry_requested")))
        setattr(scorecard, "retry_reason", llm_result.get("parse_error"))
        return scorecard

    def _select_prompt_version(
        self,
        db: Session,
        *,
        session_id: str,
        org_id: str | None = None,
    ) -> PromptVersion:
        return self.prompt_version_resolver.resolve(
            prompt_type="grading_v2",
            org_id=org_id,
            session_id=session_id,
            db=db,
        )

    def _build_effective_prompt_template(
        self,
        db: Session,
        *,
        session: DrillSession,
        prompt_template: str,
        turns: list[Any],
        session_context: dict[str, Any],
    ) -> str:
        rep = session.rep
        org_id = rep.org_id if rep is not None else None
        chunks = self._retrieve_grading_context_chunks(
            db,
            org_id=org_id,
            session=session,
            turns=turns,
            session_context=session_context,
        )
        formatted_context = self.document_retrieval_service.format_for_prompt(chunks)
        if not formatted_context:
            return ""
        return (
            f"{formatted_context}\n\n"
            "Use the retrieved company and industry playbook material above to judge call quality and technique adherence.\n"
            "Weight company-specific technique guidance over generic best practices when they conflict.\n"
            "If the transcript does not support a technique from the playbook, do not award it."
        )

    async def _grade_with_llm(
        self,
        *,
        session: DrillSession,
        prompt_template: str,
        retrieved_context: str,
        turns: list[Any],
        session_context: dict[str, Any],
        first_turn_signals: list[str],
        inflection_points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rep_turns = [t for t in turns if t.speaker.value == "rep"]
        ai_turns = [t for t in turns if t.speaker.value == "ai"]
        grading_turns = self._select_grading_turns(turns)
        fallback = self._grade_with_fallback(
            session=session,
            rep_turns=rep_turns,
            ai_turns=ai_turns,
            session_context=session_context,
            first_turn_signals=first_turn_signals,
            inflection_points=inflection_points,
        )
        technique_evaluation = fallback.get("technique_evaluation", {})
        prompt = self.prompt_builder.build(
            grading_turns,
            prompt_template=prompt_template,
            retrieved_context=retrieved_context,
            technique_evaluation=technique_evaluation,
            session_context=session_context,
            first_turn_signals=first_turn_signals,
            inflection_points=inflection_points,
        )

        if not self.settings.openai_api_key or os.getenv("PYTEST_CURRENT_TEST"):
            return {
                "status": "fallback_used",
                "grading": fallback,
                "raw_llm_response": prompt[:12000],
                "parse_error": "llm disabled for local/test execution",
                "input_token_count": None,
                "output_token_count": None,
                "model_latency_ms": 0,
                "technique_evaluation": technique_evaluation,
            }

        started = perf_counter()
        url = f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.grading_model,
            "temperature": 0.35,
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
            async with httpx.AsyncClient(timeout=self.settings.grading_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            is_timeout = isinstance(exc, httpx.TimeoutException)
            return {
                "status": "timeout_fallback" if is_timeout else "llm_error",
                "grading": fallback,
                "raw_llm_response": None,
                "parse_error": _clip_text(exc, limit=1000),
                "input_token_count": None,
                "output_token_count": None,
                "model_latency_ms": int((perf_counter() - started) * 1000),
                "retry_requested": is_timeout,
                "technique_evaluation": technique_evaluation,
            }

        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        raw_response = content if isinstance(content, str) else json.dumps(content, ensure_ascii=True)
        usage = body.get("usage", {}) if isinstance(body, dict) else {}

        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            if not isinstance(parsed, dict):
                raise ValueError("llm returned non-object payload")
            normalized = self._normalize_grading(
                parsed,
                session=session,
                first_turn_signals=first_turn_signals,
                inflection_points=inflection_points,
                fallback=fallback,
                technique_evaluation=technique_evaluation,
            )
            status = "calibrated_fallback" if bool(normalized.get("was_clamped")) else "success"
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
            "retry_requested": False,
            "technique_evaluation": technique_evaluation,
        }

    def _grade_with_fallback(
        self,
        *,
        session: DrillSession,
        rep_turns: list[Any],
        ai_turns: list[Any],
        session_context: dict[str, Any],
        first_turn_signals: list[str],
        inflection_points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self._has_meaningful_rep_evidence(rep_turns):
            return self._grade_with_no_rep_evidence(session=session)

        ordered_turns = self._ordered_turns(session.turns)
        fallback_scores = {
            key: self._score_from_signals(
                rep_turns=rep_turns,
                category_key=key,
                stage_hints=CATEGORY_STAGE_HINTS.get(key, set()),
            )
            for key in CATEGORY_KEYS
        }
        technique_evaluation = self.technique_service.evaluate(
            turns=ordered_turns,
            session_context=session_context,
            inflection_points=inflection_points,
            base_scores=fallback_scores,
        )
        checks_by_category = self._technique_checks_by_category(technique_evaluation)
        score_bands = technique_evaluation.get("bands", {})

        category_scores: dict[str, dict[str, Any]] = {}
        for key in CATEGORY_KEYS:
            band = score_bands.get(key, {})
            evidence_turn_ids = self._technique_evidence_turn_ids(
                checks_by_category=checks_by_category,
                category_key=key,
                default_turn_ids=self._fallback_evidence_turn_ids(rep_turns=rep_turns, category_key=key),
            )
            behavioral_signals = self._collect_behavioral_signals(turns=rep_turns, evidence_turn_ids=evidence_turn_ids)
            score = round(float(band.get("anchor", fallback_scores[key]) or fallback_scores[key]), 1)
            category_scores[key] = {
                "score": score,
                "confidence": 0.0,
                "rationale_summary": self._band_rationale_summary(
                    category_key=key,
                    score=score,
                    technique_checks=checks_by_category.get(key, []),
                ),
                "rationale_detail": self._band_rationale_detail(
                    category_key=key,
                    score=score,
                    technique_checks=checks_by_category.get(key, []),
                    band=band,
                ),
                "evidence_turn_ids": evidence_turn_ids,
                "behavioral_signals": behavioral_signals,
                "improvement_target": self._band_improvement_target(
                    category_key=key,
                    score=score,
                    technique_checks=checks_by_category.get(key, []),
                ),
            }

        self._apply_opening_quality_rationale(category_scores=category_scores, first_turn_signals=first_turn_signals)
        self._apply_difficulty_adjustments(category_scores=category_scores, session_context=session_context)

        overall = self._calculate_weighted_overall(category_scores)
        evidence_turn_ids = self._aggregate_evidence_turn_ids(category_scores)
        weakness_tags = self._derive_weakness_tags(category_scores=category_scores, rep_turns=rep_turns)
        highlights = self._build_technique_highlights(
            technique_evaluation=technique_evaluation,
            evidence_turn_ids=evidence_turn_ids,
        )

        base = {
            "overall_score": overall,
            "category_scores": category_scores,
            "highlights": highlights,
            "ai_summary": self._build_technique_summary(
                category_scores=category_scores,
                technique_evaluation=technique_evaluation,
                inflection_points=inflection_points,
            ),
            "evidence_turn_ids": evidence_turn_ids,
            "weakness_tags": weakness_tags,
            "evidence_quality": technique_evaluation.get("call_quality", "weak"),
            "session_complexity": self._compute_session_complexity(session),
            "score_bands": score_bands,
            "technique_checks": technique_evaluation.get("technique_checks", []),
            "call_quality": technique_evaluation.get("call_quality", "weak"),
            "grading_meta": {
                "status": "no_rep_speech" if overall == 0.0 and evidence_turn_ids == [] else "fallback_used",
                "source": "deterministic_band",
                "provisional": bool(technique_evaluation.get("provisional")),
                "confidence": 0.0,
                "evidence_quality": technique_evaluation.get("call_quality", "weak"),
                "session_complexity": self._compute_session_complexity(session),
                "call_quality": technique_evaluation.get("call_quality", "weak"),
                "message": technique_evaluation.get("message"),
            },
            "technique_evaluation": technique_evaluation,
        }
        base = self._apply_inflection_feedback(
            base,
            inflection_points=inflection_points,
            first_turn_signals=first_turn_signals,
            session_context=session_context,
        )
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
        base["grading_meta"]["confidence"] = confidence
        base["grading_meta"]["evidence_quality"] = base["evidence_quality"]
        return base

    def _score_from_signals(
        self,
        *,
        rep_turns: list[Any],
        category_key: str,
        stage_hints: set[str],
    ) -> float:
        base = 6.0
        relevant_turns = [turn for turn in rep_turns if not stage_hints or turn.stage in stage_hints] or rep_turns
        category_signals = SIGNAL_SCORE_MAP.get(category_key, {})
        turn_adjustments: list[float] = []
        for turn in relevant_turns:
            signals = [
                str(signal).strip()
                for signal in (turn.behavioral_signals or [])
                if isinstance(signal, str) and str(signal).strip()
            ]
            adjustment = 0.0
            for signal in signals:
                adjustment += category_signals.get(signal, 0.0)
            if category_key == "opening":
                signal_set = set(signals)
                if {"builds_rapport", "mentions_social_proof"}.issubset(signal_set) and "pushes_close" not in signal_set:
                    adjustment += 0.5
            turn_adjustments.append(adjustment)
        if turn_adjustments:
            base += sum(turn_adjustments) / len(turn_adjustments)
        return round(max(0.0, min(10.0, base)), 1)

    def _has_meaningful_rep_evidence(self, rep_turns: list[Any]) -> bool:
        return any(_has_meaningful_text(turn.text) for turn in rep_turns)

    def _grade_with_no_rep_evidence(self, *, session: DrillSession) -> dict[str, Any]:
        category_scores = {
            key: {
                "score": 0.0,
                "confidence": 0.0,
                "rationale_summary": "No rep speech was captured.",
                "rationale_detail": "This session did not capture enough rep speech to support grading in this category.",
                "evidence_turn_ids": [],
                "behavioral_signals": [],
                "improvement_target": self._fallback_improvement_target(key, score=0.0),
            }
            for key in CATEGORY_KEYS
        }

        return {
            "overall_score": 0.0,
            "category_scores": category_scores,
            "highlights": [
                {
                    "type": "improve",
                    "note": "No rep speech was captured, so this drill could not be meaningfully graded.",
                    "turn_id": None,
                },
                {
                    "type": "improve",
                    "note": "Run the drill again and speak through your opening, pitch, objections, and close.",
                    "turn_id": None,
                },
            ],
            "ai_summary": "No rep speech was captured in this drill, so there is not enough evidence to grade your performance.",
            "evidence_turn_ids": [],
            "weakness_tags": ["no_rep_speech", *CATEGORY_KEYS],
            "evidence_quality": "weak",
            "session_complexity": self._compute_session_complexity(session),
            "confidence_score": 0.0,
            "score_bands": {
                key: {"floor": 0.0, "ceiling": 0.0, "anchor": 0.0, "max_width": 0.0}
                for key in CATEGORY_KEYS
            },
            "technique_checks": [],
            "call_quality": "weak",
            "grading_meta": {
                "status": "no_rep_speech",
                "source": "deterministic_band",
                "provisional": False,
                "confidence": 0.0,
                "evidence_quality": "weak",
                "session_complexity": self._compute_session_complexity(session),
                "call_quality": "weak",
                "message": "No rep speech was captured in this drill.",
            },
            "technique_evaluation": {
                "technique_checks": [],
                "bands": {
                    key: {"floor": 0.0, "ceiling": 0.0, "anchor": 0.0, "max_width": 0.0}
                    for key in CATEGORY_KEYS
                },
                "call_quality": "weak",
                "call_quality_score": 0.0,
                "provisional": False,
                "message": "No rep speech was captured in this drill.",
            },
        }

    def _normalize_grading(
        self,
        payload: dict[str, Any],
        *,
        session: DrillSession,
        first_turn_signals: list[str],
        inflection_points: list[dict[str, Any]],
        fallback: dict[str, Any] | None = None,
        technique_evaluation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        turns = self._ordered_turns(session.turns)
        rep_turns = [turn for turn in turns if turn.speaker.value == "rep"]
        if not self._has_meaningful_rep_evidence(rep_turns):
            return self._grade_with_no_rep_evidence(session=session)

        valid_turn_ids = {turn.id for turn in turns}
        fallback = fallback or self._grade_with_fallback(
            session=session,
            rep_turns=rep_turns,
            ai_turns=[turn for turn in turns if turn.speaker.value == "ai"],
            session_context={},
            first_turn_signals=first_turn_signals,
            inflection_points=inflection_points,
        )
        technique_evaluation = technique_evaluation or fallback.get("technique_evaluation", {})
        score_bands = technique_evaluation.get("bands", {}) if isinstance(technique_evaluation, dict) else {}
        was_clamped = False

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

            stage_matched = self._evidence_matches_category_stage(session=session, category_key=key, evidence_turn_ids=evidence_turn_ids)
            if not stage_matched:
                evidence_turn_ids = list(fallback_category["evidence_turn_ids"])
                behavioral_signals = list(fallback_category.get("behavioral_signals", []))
                score = float(fallback_category["score"])
                was_clamped = True

            band = score_bands.get(key, {})
            if self._score_outside_band(score, band):
                score = float(fallback_category["score"])
                was_clamped = True

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

        ai_summary = _clip_text(payload.get("ai_summary"), limit=700) or fallback["ai_summary"]
        llm_weakness_tags = [
            _clip_text(tag, limit=60)
            for tag in payload.get("weakness_tags", [])
            if isinstance(tag, str) and str(tag).strip()
        ]
        derived_weakness_tags = self._derive_weakness_tags(category_scores=category_scores, rep_turns=rep_turns)
        weakness_tags = list(dict.fromkeys([*llm_weakness_tags, *derived_weakness_tags]))
        if not weakness_tags:
            weakness_tags = list(fallback["weakness_tags"])

        normalized = {
            "overall_score": overall_score,
            "category_scores": category_scores,
            "highlights": highlights,
            "ai_summary": ai_summary,
            "evidence_turn_ids": evidence_turn_ids,
            "weakness_tags": weakness_tags,
            "evidence_quality": payload.get("evidence_quality"),
            "session_complexity": payload.get("session_complexity"),
            "score_bands": score_bands,
            "technique_checks": technique_evaluation.get("technique_checks", []),
            "call_quality": technique_evaluation.get("call_quality", fallback.get("call_quality", "weak")),
        }
        normalized = self._apply_inflection_feedback(
            normalized,
            inflection_points=inflection_points,
            first_turn_signals=first_turn_signals,
            session_context={},
        )
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
        normalized["grading_meta"] = {
            "status": "provisional" if technique_evaluation.get("provisional") else "final",
            "source": "calibrated_fallback" if was_clamped else "llm_band_scored",
            "provisional": bool(technique_evaluation.get("provisional")),
            "confidence": confidence,
            "evidence_quality": normalized["evidence_quality"],
            "session_complexity": normalized.get("session_complexity"),
            "call_quality": normalized.get("call_quality"),
            "message": technique_evaluation.get("message") or ("Band-clamped to observed evidence." if was_clamped else "Score grounded in playbook technique checks."),
        }
        normalized["was_clamped"] = was_clamped

        session_complexity = normalized["session_complexity"]
        if not isinstance(session_complexity, int) or not 1 <= session_complexity <= 5:
            normalized["session_complexity"] = self._compute_session_complexity(session)
            normalized["grading_meta"]["session_complexity"] = normalized["session_complexity"]
        return normalized

    def _ordered_turns(self, turns: list[Any]) -> list[Any]:
        return sorted(
            list(turns),
            key=lambda turn: (
                int(getattr(turn, "turn_index", 0) or 0),
                str(getattr(turn, "id", "")),
            ),
        )

    def _select_grading_turns(self, turns: list[Any]) -> list[Any]:
        ordered_turns = self._ordered_turns(turns)
        if len(ordered_turns) <= MAX_TRANSCRIPT_TURNS_FOR_GRADING:
            return ordered_turns

        first_two = ordered_turns[:2]
        last_two = ordered_turns[-2:]
        middle_candidates = ordered_turns[2:-2]
        objection_turns = [
            turn
            for turn in middle_candidates
            if turn.stage == "objection_handling" or bool(getattr(turn, "objection_tags", None))
        ]
        close_turns = [turn for turn in middle_candidates if turn.stage == "close_attempt"]
        middle_slots = max(0, MAX_TRANSCRIPT_TURNS_FOR_GRADING - len(first_two) - len(last_two))
        middle = self._dedupe_turns([*objection_turns, *close_turns])[:middle_slots]
        return self._dedupe_turns([*first_two, *middle, *last_two])

    def _dedupe_turns(self, turns: list[Any]) -> list[Any]:
        seen: set[str] = set()
        ordered: list[Any] = []
        for turn in turns:
            turn_id = str(getattr(turn, "id", ""))
            key = turn_id or str(getattr(turn, "turn_index", ""))
            if key in seen:
                continue
            seen.add(key)
            ordered.append(turn)
        return ordered

    def _build_session_context(
        self,
        *,
        db: Session,
        session: DrillSession,
        turns: list[Any],
        timeline: ReconstructedTimeline,
    ) -> dict[str, Any]:
        scenario = db.scalar(select(Scenario).where(Scenario.id == session.scenario_id))
        difficulty = max(1, min(5, int(getattr(scenario, "difficulty", 1) or 1)))
        pressure_values = [int(timeline.final_state.objection_pressure or 0)]
        pressure_values.extend(int(context.pressure_before or 0) for context in timeline.turn_contexts)
        pressure_values.extend(int(context.pressure_after or 0) for context in timeline.turn_contexts)
        objections_resolved = _dedupe_text(
            [tag for context in timeline.turn_contexts for tag in context.resolved_objections]
        )
        return {
            "difficulty": difficulty,
            "emotion_trajectory": self._emotion_trajectory(timeline=timeline, turns=turns),
            "peak_resistance": max(pressure_values or [0]),
            "objections_resolved": objections_resolved,
            "total_rep_turns": len([turn for turn in turns if turn.speaker.value == "rep"]),
        }

    def _emotion_trajectory(self, *, timeline: ReconstructedTimeline, turns: list[Any]) -> list[str]:
        raw: list[str] = []
        if timeline.turn_contexts:
            raw.append(str(timeline.turn_contexts[0].emotion_before or "").strip())
            raw.extend(str(context.emotion_after or "").strip() for context in timeline.turn_contexts)
        else:
            raw.extend(
                str(getattr(turn, "emotion_after", "") or "").strip()
                for turn in turns
                if turn.speaker.value == "ai"
            )

        trajectory: list[str] = []
        for emotion in raw:
            if not emotion:
                continue
            if not trajectory or trajectory[-1] != emotion:
                trajectory.append(emotion)
        return trajectory

    def _first_turn_signals(self, *, turns: list[Any], timeline: ReconstructedTimeline) -> list[str]:
        if timeline.turn_contexts:
            return _dedupe_text(list(timeline.turn_contexts[0].behavioral_signals))
        rep_turn = next((turn for turn in turns if turn.speaker.value == "rep"), None)
        if rep_turn is None:
            return []
        return _dedupe_text([str(item) for item in (rep_turn.behavioral_signals or []) if str(item).strip()])

    def _resolve_inflection_points(
        self,
        *,
        db: Session,
        session_id: str,
        timeline: ReconstructedTimeline,
    ) -> list[dict[str, Any]]:
        artifact = db.scalar(
            select(SessionArtifact)
            .where(SessionArtifact.session_id == session_id, SessionArtifact.artifact_type == "inflection_points")
            .order_by(SessionArtifact.created_at.desc())
        )
        if artifact is not None:
            metadata = artifact.metadata_json if isinstance(artifact.metadata_json, dict) else {}
            raw_points = metadata.get("points", [])
            if isinstance(raw_points, list):
                return [point for point in raw_points if isinstance(point, dict)]
        return [asdict(point) for point in self.inflection_point_service.analyze(timeline)]

    def _apply_opening_quality_rationale(
        self,
        *,
        category_scores: dict[str, dict[str, Any]],
        first_turn_signals: list[str],
    ) -> None:
        label = _opening_quality_label(first_turn_signals)
        if label is None:
            return

        if label == "damaging opener":
            self._append_rationale_detail(
                category_scores,
                "opening",
                "The opening created unnecessary resistance immediately.",
            )
            self._append_rationale_detail(
                category_scores,
                "professionalism",
                "The early pushiness made the interaction feel less professional.",
            )
            self._append_rationale_detail(
                category_scores,
                "objection_handling",
                "The rep then had to work against resistance created by the opener.",
            )
            self._append_rationale_detail(
                category_scores,
                "closing_technique",
                "Closing attempts happened under resistance the rep partly created.",
            )
            self._adjust_category_score(category_scores, "opening", -0.7)
            self._adjust_category_score(category_scores, "professionalism", -0.4)
            return

        if label == "weak opener":
            self._append_rationale_detail(
                category_scores,
                "opening",
                "The opening was generic and did not create much early momentum.",
            )
            self._adjust_category_score(category_scores, "opening", -0.3)
            return

        if label == "strong opener":
            self._append_rationale_detail(
                category_scores,
                "opening",
                "The opener created rapport and lowered friction early.",
            )
            self._append_rationale_detail(
                category_scores,
                "professionalism",
                "The early tone helped the rep sound calm and credible.",
            )
            self._adjust_category_score(category_scores, "opening", 0.4)
            self._adjust_category_score(category_scores, "professionalism", 0.3)

    def _apply_difficulty_adjustments(
        self,
        *,
        category_scores: dict[str, dict[str, Any]],
        session_context: dict[str, Any],
    ) -> None:
        if not session_context:
            return

        difficulty = int(session_context.get("difficulty", 1) or 1)
        peak_resistance = int(session_context.get("peak_resistance", 0) or 0)
        resolved_count = len(session_context.get("objections_resolved", []) or [])
        trajectory = [str(item) for item in session_context.get("emotion_trajectory", []) if str(item).strip()]
        recovery_arc = self._has_recovery_arc(trajectory)

        if difficulty >= 4 and peak_resistance >= 4:
            self._append_rationale_detail(
                category_scores,
                "objection_handling",
                "This came against high homeowner resistance, so successful movement deserves extra credit.",
            )
            self._adjust_category_score(category_scores, "objection_handling", 0.4)

        if difficulty >= 4 and recovery_arc:
            self._append_rationale_detail(
                category_scores,
                "objection_handling",
                "The rep earned a real recovery arc against a hard homeowner.",
            )
            self._adjust_category_score(category_scores, "objection_handling", 0.5)

        if difficulty >= 4 and resolved_count >= 2:
            self._append_rationale_detail(
                category_scores,
                "professionalism",
                "The rep stayed composed long enough to resolve multiple objections in a hard scenario.",
            )
            self._adjust_category_score(category_scores, "professionalism", 0.2)

    def _apply_inflection_feedback(
        self,
        grading: dict[str, Any],
        *,
        inflection_points: list[dict[str, Any]],
        first_turn_signals: list[str],
        session_context: dict[str, Any],
    ) -> dict[str, Any]:
        del first_turn_signals
        highlights = list(grading.get("highlights") or [])
        negative_points = [point for point in inflection_points if point.get("direction") == "negative"][:2]
        positive_points = [
            point
            for point in inflection_points
            if point.get("direction") == "positive" and str(point.get("emotion_after") or "") in POSITIVE_RECOVERY_EMOTIONS
        ]

        prioritized: list[dict[str, Any]] = []
        for point in negative_points:
            turn_index = point.get("turn_index", "?")
            note = str(point.get("coaching_note") or "").strip()
            prioritized.append(
                {
                    "type": "improve",
                    "note": _clip_text(f"Turn {turn_index} was where you lost them: {note}", limit=240),
                    "turn_id": point.get("rep_turn_id") or point.get("ai_turn_id") or None,
                }
            )
        for point in positive_points[:2]:
            turn_index = point.get("turn_index", "?")
            note = str(point.get("coaching_note") or "").strip()
            prioritized.append(
                {
                    "type": "strong",
                    "note": _clip_text(f"Turn {turn_index} turned it around: {note}", limit=240),
                    "turn_id": point.get("rep_turn_id") or point.get("ai_turn_id") or None,
                }
            )

        if not positive_points and self._has_recovery_arc(session_context.get("emotion_trajectory", []) or []):
            prioritized.append(
                {
                    "type": "strong",
                    "note": _clip_text(
                        "You created a real recovery arc and softened the homeowner after a hard moment.",
                        limit=240,
                    ),
                    "turn_id": None,
                }
            )

        merged_highlights: list[dict[str, Any]] = []
        for item in prioritized + highlights:
            if not isinstance(item, dict):
                continue
            note = _clip_text(item.get("note"), limit=240)
            if not note:
                continue
            highlight = {
                "type": item.get("type") if item.get("type") in {"strong", "improve"} else "improve",
                "note": note,
                "turn_id": item.get("turn_id"),
            }
            if any(existing["note"] == highlight["note"] for existing in merged_highlights):
                continue
            merged_highlights.append(highlight)
            if len(merged_highlights) == 4:
                break
        if len(merged_highlights) >= 2:
            grading["highlights"] = merged_highlights

        summary = str(grading.get("ai_summary") or "").strip()
        if negative_points:
            top = negative_points[0]
            prefix = _clip_text(
                f"Turn {top.get('turn_index', '?')} was where you lost them: {top.get('coaching_note', '')}",
                limit=180,
            )
            summary = f"{prefix} {summary}".strip()
        elif positive_points:
            top = positive_points[0]
            prefix = _clip_text(
                f"Turn {top.get('turn_index', '?')} turned the conversation around: {top.get('coaching_note', '')}",
                limit=180,
            )
            summary = f"{prefix} {summary}".strip()
        elif self._has_recovery_arc(session_context.get("emotion_trajectory", []) or []):
            summary = (
                "You earned a real recovery arc against a difficult homeowner. "
                + summary
            ).strip()
        grading["ai_summary"] = _clip_text(summary, limit=700)
        return grading

    def _has_recovery_arc(self, trajectory: list[str]) -> bool:
        emotions = [str(item) for item in trajectory if str(item).strip()]
        if not emotions:
            return False
        hard_indices = [index for index, emotion in enumerate(emotions) if emotion in {"hostile", "annoyed"}]
        if not hard_indices:
            return False
        return any(
            later in {"neutral", "curious", "interested"}
            for index in hard_indices
            for later in emotions[index + 1 :]
        )

    def _append_rationale_detail(
        self,
        category_scores: dict[str, dict[str, Any]],
        category_key: str,
        addition: str,
    ) -> None:
        category = category_scores.get(category_key)
        if not isinstance(category, dict):
            return
        detail = _clip_text(category.get("rationale_detail"), limit=320)
        combined = f"{detail} {addition}".strip() if detail else addition
        category["rationale_detail"] = _clip_text(combined, limit=400)

    def _adjust_category_score(
        self,
        category_scores: dict[str, dict[str, Any]],
        category_key: str,
        delta: float,
    ) -> None:
        category = category_scores.get(category_key)
        if not isinstance(category, dict):
            return
        score = float(category.get("score", 0.0) or 0.0)
        category["score"] = round(max(0.0, min(10.0, score + delta)), 1)

    def _derive_weakness_tags(
        self,
        *,
        category_scores: dict[str, Any],
        rep_turns: list[Any],
    ) -> list[str]:
        tags: set[str] = set()
        for key, value in category_scores.items():
            score = _score_value(value)
            if score is not None and float(score) < 6.5:
                tags.add(key)

        signal_counts: dict[str, int] = {}
        for turn in rep_turns:
            for signal in (turn.behavioral_signals or []):
                if not isinstance(signal, str) or not signal.strip():
                    continue
                signal_counts[signal] = signal_counts.get(signal, 0) + 1

        for tag, triggers in WEAKNESS_TAG_SIGNAL_TRIGGERS.items():
            if any(signal_counts.get(signal, 0) >= WEAKNESS_TAG_SIGNAL_THRESHOLD for signal in triggers):
                tags.add(tag)

        return sorted(tags)

    def compute_confidence(self, session: DrillSession, grading: dict[str, Any]) -> float:
        rep_turns = [t for t in session.turns if t.speaker.value == "rep"]
        if not self._has_meaningful_rep_evidence(rep_turns):
            return 0.0
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

    def _retrieve_grading_context_chunks(
        self,
        db: Session,
        *,
        org_id: str | None,
        session: DrillSession,
        turns: list[Any],
        session_context: dict[str, Any],
    ) -> list[Any]:
        scenario = db.scalar(select(Scenario).where(Scenario.id == session.scenario_id))
        context_hint_parts: list[str] = []
        if scenario is not None:
            context_hint_parts.append(scenario.name)
            context_hint_parts.append(f"difficulty {scenario.difficulty}")
        context_hint = " ".join(part for part in context_hint_parts if part).strip()
        objection_tags = _dedupe_text(
            [
                str(tag)
                for turn in turns
                for tag in getattr(turn, "objection_tags", []) or []
                if str(tag).strip()
            ]
        )
        topics = [
            "opening low pressure neighborhood social proof route framing call quality grading",
            "feature benefit soft close value pitch property specific evidence pricing framing grading",
        ]
        if objection_tags:
            for tag in objection_tags[:3]:
                topics.append(f"objection handling {tag} validate pivot yes question address close grading")
        if any(turn.speaker.value == "rep" and turn.stage in {"initial_pitch", "pitch", "value_prop"} for turn in turns):
            topics.append("bimonthly monthly quarterly value anchor eco friendly no contract differentiators grading")
        if any(turn.speaker.value == "rep" and turn.stage in {"close_attempt", "closing"} for turn in turns):
            topics.append("option close assumptive close assignment close backyard close level up moment grading")
        if int(session_context.get("peak_resistance", 0) or 0) >= 4:
            topics.append("psychology reactance decision fatigue hard pressure closing grading")

        rows: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for topic in topics:
            for chunk in self.document_retrieval_service.retrieve_for_topic(
                db,
                org_id=org_id,
                topic=topic,
                context_hint=context_hint,
                k=2,
                min_score=0.70,
            ):
                chunk_key = (str(getattr(chunk, "document_id", "")), str(getattr(chunk, "chunk_id", "")))
                if chunk_key in seen:
                    continue
                seen.add(chunk_key)
                rows.append(chunk)
                if len(rows) >= 8:
                    return rows
        return rows

    def _write_technique_artifact(
        self,
        db: Session,
        *,
        session_id: str,
        grading: dict[str, Any],
        technique_evaluation: dict[str, Any] | None,
        grading_status: str,
        retry_requested: bool,
    ) -> None:
        artifact = db.scalar(
            select(SessionArtifact)
            .where(
                SessionArtifact.session_id == session_id,
                SessionArtifact.artifact_type == TECHNIQUE_EVAL_ARTIFACT_TYPE,
            )
            .order_by(SessionArtifact.created_at.desc())
        )
        if artifact is None:
            artifact = SessionArtifact(
                session_id=session_id,
                artifact_type=TECHNIQUE_EVAL_ARTIFACT_TYPE,
                storage_key=f"session-artifacts/{session_id}/{TECHNIQUE_EVAL_ARTIFACT_TYPE}.json",
                metadata_json={},
            )
            db.add(artifact)
        artifact.metadata_json = {
            "grading_status": grading_status,
            "retry_requested": retry_requested,
            "grading_meta": grading.get("grading_meta", {}),
            "technique_checks": (technique_evaluation or {}).get("technique_checks", grading.get("technique_checks", [])),
            "score_bands": (technique_evaluation or {}).get("bands", grading.get("score_bands", {})),
            "call_quality": (technique_evaluation or {}).get("call_quality", grading.get("call_quality")),
            "message": (technique_evaluation or {}).get("message"),
        }
        db.flush()

    def _technique_checks_by_category(self, technique_evaluation: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_KEYS}
        for item in technique_evaluation.get("technique_checks", []):
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "").strip()
            if category not in grouped:
                continue
            grouped[category].append(item)
        return grouped

    def _technique_evidence_turn_ids(
        self,
        *,
        checks_by_category: dict[str, list[dict[str, Any]]],
        category_key: str,
        default_turn_ids: list[str],
    ) -> list[str]:
        evidence_turn_ids: list[str] = []
        for item in checks_by_category.get(category_key, []):
            if item.get("status") not in {"hit", "partial"}:
                continue
            evidence_turn_ids.extend(
                turn_id
                for turn_id in item.get("evidence_turn_ids", [])
                if isinstance(turn_id, str) and turn_id
            )
        return list(dict.fromkeys(evidence_turn_ids or default_turn_ids))[:3]

    def _band_rationale_summary(
        self,
        *,
        category_key: str,
        score: float,
        technique_checks: list[dict[str, Any]],
    ) -> str:
        positives = [item["label"] for item in technique_checks if item.get("status") in {"hit", "partial"} and item.get("kind") == "reward"]
        negatives = [item["label"] for item in technique_checks if item.get("status") in {"hit", "miss"} and item.get("kind") == "cap"]
        if positives and score >= 7.5:
            return _clip_text(f"Playbook-aligned on {positives[0].lower()}.", limit=80)
        if negatives:
            return _clip_text(f"Lost points on {negatives[0].lower()}.", limit=80)
        if positives:
            return _clip_text(f"Partial strength on {positives[0].lower()}.", limit=80)
        return self._fallback_rationale_summary(category_key, score=score)

    def _band_rationale_detail(
        self,
        *,
        category_key: str,
        score: float,
        technique_checks: list[dict[str, Any]],
        band: dict[str, Any],
    ) -> str:
        positives = [item["label"] for item in technique_checks if item.get("status") in {"hit", "partial"} and item.get("kind") == "reward"]
        misses = [item["label"] for item in technique_checks if item.get("status") in {"miss", "hit"} and item.get("kind") == "cap"]
        details: list[str] = []
        if positives:
            details.append(f"You showed {positives[0].lower()} in the recorded evidence.")
        if len(positives) > 1:
            details.append(f"You also showed {positives[1].lower()}.")
        if misses:
            details.append(f"The main limiter was {misses[0].lower()}.")
        floor = band.get("floor")
        ceiling = band.get("ceiling")
        if floor is not None and ceiling is not None:
            details.append(f"This category stayed inside a {float(floor):.1f}-{float(ceiling):.1f} playbook band.")
        if not details:
            return self._fallback_rationale_detail(category_key, score=score)
        return _clip_text(" ".join(details), limit=400)

    def _band_improvement_target(
        self,
        *,
        category_key: str,
        score: float,
        technique_checks: list[dict[str, Any]],
    ) -> str | None:
        if score >= 8.0:
            return None
        missed_reward = next(
            (
                item
                for item in technique_checks
                if item.get("status") == "miss" and item.get("kind") == "reward"
            ),
            None,
        )
        if missed_reward is not None:
            return _clip_text(f"Sharpen {str(missed_reward['label']).lower()}", limit=60)
        cap_item = next(
            (
                item
                for item in technique_checks
                if item.get("status") == "hit" and item.get("kind") == "cap"
            ),
            None,
        )
        if cap_item is not None:
            return _clip_text(f"Remove {str(cap_item['label']).lower()}", limit=60)
        return self._fallback_improvement_target(category_key, score=score)

    def _build_technique_highlights(
        self,
        *,
        technique_evaluation: dict[str, Any],
        evidence_turn_ids: list[str],
    ) -> list[dict[str, Any]]:
        strong = next(
            (
                item
                for item in technique_evaluation.get("technique_checks", [])
                if isinstance(item, dict) and item.get("status") == "hit" and item.get("kind") == "reward"
            ),
            None,
        )
        improve = next(
            (
                item
                for item in technique_evaluation.get("technique_checks", [])
                if isinstance(item, dict)
                and ((item.get("status") == "miss" and item.get("kind") == "reward") or (item.get("status") == "hit" and item.get("kind") == "cap"))
            ),
            None,
        )
        highlights: list[dict[str, Any]] = []
        if strong is not None:
            strong_turn = next((turn_id for turn_id in strong.get("evidence_turn_ids", []) if isinstance(turn_id, str)), None)
            highlights.append(
                {
                    "type": "strong",
                    "note": _clip_text(f"You landed {str(strong['label']).lower()} and gave the homeowner something concrete to follow.", limit=240),
                    "turn_id": strong_turn or (evidence_turn_ids[0] if evidence_turn_ids else None),
                }
            )
        if improve is not None:
            improve_turn = next((turn_id for turn_id in improve.get("evidence_turn_ids", []) if isinstance(turn_id, str)), None)
            highlights.append(
                {
                    "type": "improve",
                    "note": _clip_text(f"The call dropped on {str(improve['label']).lower()} - tighten that moment next time.", limit=240),
                    "turn_id": improve_turn or (evidence_turn_ids[-1] if evidence_turn_ids else None),
                }
            )
        if len(highlights) < 2:
            highlights.append(
                {
                    "type": "strong",
                    "note": "You created enough structure for the grader to link specific evidence to the call.",
                    "turn_id": evidence_turn_ids[0] if evidence_turn_ids else None,
                }
            )
        if len(highlights) < 2:
            highlights.append(
                {
                    "type": "improve",
                    "note": "Make the next step more direct once you have addressed the active concern.",
                    "turn_id": evidence_turn_ids[-1] if evidence_turn_ids else None,
                }
            )
        return highlights[:4]

    def _build_technique_summary(
        self,
        *,
        category_scores: dict[str, dict[str, Any]],
        technique_evaluation: dict[str, Any],
        inflection_points: list[dict[str, Any]],
    ) -> str:
        strongest_key = max(CATEGORY_KEYS, key=lambda key: float(category_scores.get(key, {}).get("score", 0.0) or 0.0))
        weakest_key = min(CATEGORY_KEYS, key=lambda key: float(category_scores.get(key, {}).get("score", 10.0) or 10.0))
        strongest_label = strongest_key.replace("_", " ")
        weakest_target = category_scores.get(weakest_key, {}).get("improvement_target") or self._fallback_improvement_target(weakest_key, score=float(category_scores.get(weakest_key, {}).get("score", 0.0) or 0.0)) or "tighten the next-step ask"
        strongest_check = next(
            (
                item
                for item in technique_evaluation.get("technique_checks", [])
                if isinstance(item, dict)
                and item.get("category") == strongest_key
                and item.get("status") in {"hit", "partial"}
            ),
            None,
        )
        sentence_one = (
            f"You were strongest in {strongest_label} because {str(strongest_check['label']).lower()} showed up in the evidence."
            if strongest_check
            else f"You were strongest in {strongest_label}, and that gave the call some real structure."
        )
        negative_point = next((point for point in inflection_points if point.get("direction") == "negative"), None)
        if negative_point is not None:
            sentence_two = _clip_text(
                f"Turn {negative_point.get('turn_index', '?')} was where things slipped: {negative_point.get('coaching_note', '')}",
                limit=220,
            )
        else:
            sentence_two = "The biggest dip came when the call stopped moving forward and the next step stayed too soft."
        sentence_three = f"Next time, {str(weakest_target).rstrip('.').lower()}."
        return _clip_text(f"{sentence_one} {sentence_two} {sentence_three}", limit=700)

    def _evidence_matches_category_stage(
        self,
        *,
        session: DrillSession,
        category_key: str,
        evidence_turn_ids: list[str],
    ) -> bool:
        if not evidence_turn_ids:
            return False
        stage_hints = CATEGORY_STAGE_HINTS.get(category_key, set())
        if not stage_hints:
            return True
        return any(
            turn.id in set(evidence_turn_ids) and turn.stage in stage_hints
            for turn in session.turns
        )

    def _score_outside_band(self, score: float, band: dict[str, Any]) -> bool:
        if not isinstance(band, dict) or not band:
            return False
        floor = band.get("floor")
        ceiling = band.get("ceiling")
        if floor is None or ceiling is None:
            return False
        return float(score) < float(floor) - 0.05 or float(score) > float(ceiling) + 0.05

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
