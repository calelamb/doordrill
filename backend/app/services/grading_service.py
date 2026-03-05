from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scorecard import Scorecard
from app.models.session import Session
from app.models.types import SessionStatus


class GradingService:
    """Async grading stub wired for LLM-as-judge provider integration."""

    async def grade_session(self, db: Session, session_id: str) -> Scorecard:
        session = db.scalar(select(Session).where(Session.id == session_id))
        if session is None:
            raise ValueError("session not found")

        turns = session.turns
        rep_turns = [t for t in turns if t.speaker.value == "rep"]
        ai_turns = [t for t in turns if t.speaker.value == "ai"]
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
        overall = round(sum(category_scores.values()) / len(category_scores), 2)

        evidence = [t.id for t in rep_turns[:3]]
        highlights = [
            {"type": "strong", "note": "Strong rapport and pacing.", "turn_id": evidence[0] if evidence else None},
            {
                "type": "improve",
                "note": "Push for a clearer close when interest appears.",
                "turn_id": evidence[-1] if evidence else None,
            },
        ]

        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        if scorecard is None:
            scorecard = Scorecard(
                session_id=session_id,
                overall_score=overall,
                category_scores=category_scores,
                highlights=highlights,
                ai_summary="Solid drill. Improve explicit close attempts and objection reframing.",
                evidence_turn_ids=[e for e in evidence if e],
            )
            db.add(scorecard)
        else:
            scorecard.overall_score = overall
            scorecard.category_scores = category_scores
            scorecard.highlights = highlights
            scorecard.ai_summary = "Updated scorecard generated from latest transcript."
            scorecard.evidence_turn_ids = [e for e in evidence if e]

        session.status = SessionStatus.GRADED
        session.ended_at = session.ended_at or datetime.now(timezone.utc)
        db.commit()
        db.refresh(scorecard)
        return scorecard
