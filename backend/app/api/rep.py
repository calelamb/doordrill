from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus
from app.schemas.assignment import AssignmentResponse
from app.schemas.session import SessionCreateRequest, SessionResponse

router = APIRouter(prefix="/rep", tags=["rep"])


@router.get("/assignments", response_model=list[AssignmentResponse])
def get_rep_assignments(rep_id: str = Query(...), db: Session = Depends(get_db)) -> list[Assignment]:
    return db.scalars(select(Assignment).where(Assignment.rep_id == rep_id).order_by(Assignment.created_at.desc())).all()


@router.post("/sessions", response_model=SessionResponse)
def create_session(payload: SessionCreateRequest, db: Session = Depends(get_db)) -> DrillSession:
    assignment = db.scalar(select(Assignment).where(Assignment.id == payload.assignment_id))
    if assignment is None:
        raise HTTPException(status_code=404, detail="assignment not found")

    session = DrillSession(
        assignment_id=payload.assignment_id,
        rep_id=payload.rep_id,
        scenario_id=payload.scenario_id,
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.ACTIVE,
    )
    assignment.status = AssignmentStatus.IN_PROGRESS
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions/{session_id}")
def get_session_with_feedback(session_id: str, db: Session = Depends(get_db)) -> dict:
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
    return {
        "session": SessionResponse.model_validate(session).model_dump(),
        "scorecard": (
            {
                "id": scorecard.id,
                "overall_score": scorecard.overall_score,
                "category_scores": scorecard.category_scores,
                "highlights": scorecard.highlights,
                "ai_summary": scorecard.ai_summary,
                "evidence_turn_ids": scorecard.evidence_turn_ids,
            }
            if scorecard
            else None
        ),
    }
