from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.types import TurnSpeaker
from app.services.grading_service import GradingService
from tests.transcript_pipeline_helpers import create_assignment_and_session


@pytest.mark.asyncio
async def test_grade_session_returns_zero_score_when_no_rep_speech(seed_org):
    _, session_id = create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        assert session is not None

        ai_turn = SessionTurn(
            session_id=session.id,
            turn_index=1,
            speaker=TurnSpeaker.AI,
            stage="door_knock",
            text="Hello?",
            started_at=session.started_at,
            ended_at=session.started_at + timedelta(seconds=2),
            objection_tags=[],
        )
        db.add(ai_turn)
        db.commit()

        scorecard = await GradingService().grade_session(db, session_id=session_id)

        assert scorecard.overall_score == 0.0
        assert scorecard.weakness_tags[0] == "no_rep_speech"
        assert all(category["score"] == 0.0 for category in scorecard.category_scores.values())
        assert scorecard.ai_summary.startswith("No rep speech was captured")
    finally:
        db.close()
