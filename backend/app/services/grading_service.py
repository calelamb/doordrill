from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import SessionStatus
from app.schemas.scorecard import StructuredScorecardPayload

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


class GradingPromptBuilder:
    @classmethod
    def template_blueprint(cls) -> str:
        return (
            "Return valid JSON only.\n"
            "Use category_scores with keys opening, pitch_delivery, objection_handling, closing_technique, professionalism.\n"
            "Each category must contain score, rationale, and evidence_turn_ids.\n"
            "Compute weighted overall_score using 15/25/30/20/10 weights.\n"
            "Provide 2-4 highlights using type strong|improve, plus a plain-English second-person ai_summary."
        )

    def build(self, turns: list[Any]) -> str:
        transcript_rows = [
            f'{turn.turn_index}. ({turn.id}) [{turn.speaker.value}/{turn.stage}] "{turn.text}"'
            for turn in turns
        ]
        transcript_text = "\n".join(transcript_rows) or "No transcript turns captured."
        schema = StructuredScorecardPayload.model_json_schema()
        return (
            "You are grading a door-to-door sales training session.\n"
            "Be evidence-based, strict, and specific.\n"
            "Return valid JSON only.\n"
            "All evidence_turn_ids must refer to turn ids that appear in the transcript.\n"
            "The ai_summary must be plain English, written directly to the rep in second person.\n"
            "Highlights must contain 2 to 4 items with type 'strong' or 'improve'.\n"
            "Use these weighted category rules:\n"
            "- opening: 15%\n"
            "- pitch_delivery: 25%\n"
            "- objection_handling: 30%\n"
            "- closing_technique: 20%\n"
            "- professionalism: 10%\n"
            "Use this JSON schema shape:\n"
            f"{json.dumps(schema, ensure_ascii=True)}\n"
            "Transcript:\n"
            f"{transcript_text}"
        )


class GradingService:
    """Async grading service with provider-backed judge plus deterministic fallback."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.prompt_builder = GradingPromptBuilder()

    async def grade_session(self, db: Session, session_id: str) -> Scorecard:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        if session is None:
            raise ValueError("session not found")

        turns = session.turns
        rep_turns = [t for t in turns if t.speaker.value == "rep"]
        ai_turns = [t for t in turns if t.speaker.value == "ai"]
        grading = await self._grade_with_llm(turns)
        if grading is None:
            grading = self._grade_with_fallback(rep_turns=rep_turns, ai_turns=ai_turns)

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
                category_scores=category_scores,
                highlights=highlights,
                ai_summary=ai_summary,
                evidence_turn_ids=[e for e in evidence if e],
                weakness_tags=weakness_tags,
            )
            db.add(scorecard)
        else:
            scorecard.overall_score = overall
            scorecard.category_scores = category_scores
            scorecard.highlights = highlights
            scorecard.ai_summary = ai_summary
            scorecard.evidence_turn_ids = [e for e in evidence if e]
            scorecard.weakness_tags = weakness_tags

        session.status = SessionStatus.GRADED
        session.ended_at = session.ended_at or datetime.now(timezone.utc)
        db.commit()
        db.refresh(scorecard)
        return scorecard

    async def _grade_with_llm(self, turns: list[Any]) -> dict[str, Any] | None:
        if not self.settings.openai_api_key or os.getenv("PYTEST_CURRENT_TEST"):
            return None

        prompt = self.prompt_builder.build(turns)

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
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = json.loads(content) if isinstance(content, str) else None
            if not isinstance(parsed, dict):
                return None
            return self._normalize_grading(parsed, turns)
        except Exception:
            return None

    def _grade_with_fallback(self, *, rep_turns: list[Any], ai_turns: list[Any]) -> dict[str, Any]:
        depth = max(1, len(rep_turns))
        opening = min(10.0, 6.0 + depth * 0.3)
        pitch = min(10.0, 5.5 + depth * 0.35)
        objections = min(10.0, 5.0 + len([t for t in rep_turns if "price" in t.text.lower()]) * 1.0)
        closing = min(10.0, 5.0 + len([t for t in rep_turns if "schedule" in t.text.lower() or "today" in t.text.lower()]) * 1.2)
        professionalism = min(10.0, 6.5 + (0.2 if len(ai_turns) > 0 else 0.0))

        category_scores = {
            "opening": round(opening, 1),
            "pitch_delivery": round(pitch, 1),
            "objection_handling": round(objections, 1),
            "closing_technique": round(closing, 1),
            "professionalism": round(professionalism, 1),
        }
        overall = self._calculate_weighted_overall(category_scores)
        weakness_tags = [key for key, score in category_scores.items() if score < 7.0]
        if not weakness_tags and overall < 8.0:
            weakness_tags = ["consistency"]

        evidence = [t.id for t in rep_turns[:3]]
        highlights = [
            {"type": "strong", "note": "Strong rapport and pacing.", "turn_id": evidence[0] if evidence else None},
            {
                "type": "improve",
                "note": "Push for a clearer close when interest appears.",
                "turn_id": evidence[-1] if evidence else None,
            },
        ]

        return {
            "overall_score": overall,
            "category_scores": category_scores,
            "highlights": highlights,
            "ai_summary": "You handled the drill with decent control, but you need a clearer close and more direct objection reframing.",
            "evidence_turn_ids": [e for e in evidence if e],
            "weakness_tags": weakness_tags,
        }

    def _normalize_grading(self, payload: dict[str, Any], turns: list[Any]) -> dict[str, Any]:
        valid_turn_ids = {turn.id for turn in turns}
        fallback = self._grade_with_fallback(
            rep_turns=[turn for turn in turns if turn.speaker.value == "rep"],
            ai_turns=[turn for turn in turns if turn.speaker.value == "ai"],
        )

        category_scores: dict[str, float] = {}
        raw_scores = payload.get("category_scores", {})
        for key in CATEGORY_KEYS:
            source = raw_scores.get(key) if isinstance(raw_scores, dict) else fallback["category_scores"][key]
            if isinstance(source, dict):
                source = source.get("score")
            try:
                value = float(source)
            except Exception:
                value = float(fallback["category_scores"][key])
            category_scores[key] = round(max(0.0, min(10.0, value)), 1)

        overall = payload.get("overall_score")
        try:
            overall_score = round(max(0.0, min(10.0, float(overall))), 2)
        except Exception:
            overall_score = self._calculate_weighted_overall(category_scores)

        raw_highlights = payload.get("highlights", [])
        highlights = []
        if isinstance(raw_highlights, list):
            for item in raw_highlights[:3]:
                if not isinstance(item, dict):
                    continue
                note = str(item.get("note", "")).strip()
                if not note:
                    continue
                turn_id = item.get("turn_id")
                if turn_id not in valid_turn_ids:
                    turn_id = None
                highlight_type = str(item.get("type", "improve")).strip() or "improve"
                highlights.append({"type": highlight_type, "note": note[:240], "turn_id": turn_id})
        if not highlights:
            highlights = fallback["highlights"]

        evidence_turn_ids = [
            turn_id
            for turn_id in payload.get("evidence_turn_ids", [])
            if isinstance(turn_id, str) and turn_id in valid_turn_ids
        ]
        if not evidence_turn_ids and isinstance(raw_scores, dict):
            evidence_turn_ids = []
            for key in CATEGORY_KEYS:
                category_payload = raw_scores.get(key)
                if not isinstance(category_payload, dict):
                    continue
                evidence_turn_ids.extend(
                    turn_id
                    for turn_id in category_payload.get("evidence_turn_ids", [])
                    if isinstance(turn_id, str) and turn_id in valid_turn_ids
                )
            evidence_turn_ids = list(dict.fromkeys(evidence_turn_ids))
        if not evidence_turn_ids:
            evidence_turn_ids = fallback["evidence_turn_ids"]

        ai_summary = str(payload.get("ai_summary", "")).strip()[:400] or fallback["ai_summary"]
        weakness_tags = [
            str(tag).strip()
            for tag in payload.get("weakness_tags", [])
            if isinstance(tag, str) and str(tag).strip()
        ]
        if not weakness_tags:
            weakness_tags = [key for key, value in category_scores.items() if value < 7.0] or fallback["weakness_tags"]

        return {
            "overall_score": overall_score,
            "category_scores": category_scores,
            "highlights": highlights,
            "ai_summary": ai_summary,
            "evidence_turn_ids": evidence_turn_ids,
            "weakness_tags": weakness_tags,
        }

    def _calculate_weighted_overall(self, category_scores: dict[str, float]) -> float:
        total = sum(float(category_scores.get(key, 0.0)) * weight for key, weight in CATEGORY_WEIGHTS.items())
        return round(max(0.0, min(10.0, total)), 2)
