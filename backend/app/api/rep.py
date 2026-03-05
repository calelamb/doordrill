from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_rep_or_manager
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus
from app.schemas.assignment import AssignmentResponse
from app.schemas.session import SessionCreateRequest, SessionResponse

router = APIRouter(prefix="/rep", tags=["rep"])


@router.get("/assignments", response_model=list[AssignmentResponse])
def get_rep_assignments(
    rep_id: str = Query(...),
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> list[Assignment]:
    if actor.user_id and actor.role == "rep" and actor.user_id != rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own assignments")

    return db.scalars(select(Assignment).where(Assignment.rep_id == rep_id).order_by(Assignment.created_at.desc())).all()


@router.post("/sessions", response_model=SessionResponse)
def create_session(
    payload: SessionCreateRequest,
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> DrillSession:
    if actor.user_id and actor.role == "rep" and actor.user_id != payload.rep_id:
        raise HTTPException(status_code=403, detail="rep can only start their own session")

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
def get_session_with_feedback(
    session_id: str,
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    if actor.user_id and actor.role == "rep" and actor.user_id != session.rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own sessions")

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
                "weakness_tags": scorecard.weakness_tags,
            }
            if scorecard
            else None
        ),
    }
