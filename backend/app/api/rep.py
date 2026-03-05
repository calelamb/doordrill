from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_rep_or_manager
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus
from app.models.user import User
from app.schemas.assignment import AssignmentResponse
from app.schemas.notification import DeviceTokenCreateRequest, DeviceTokenResponse
from app.schemas.session import SessionCreateRequest, SessionResponse
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/rep", tags=["rep"])
notification_service = NotificationService()


def _get_user_or_404(db: Session, user_id: str, label: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return user


def _ensure_same_org(actor: Actor, org_id: str | None) -> None:
    if actor.org_id and org_id and actor.org_id != org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")


@router.get("/assignments", response_model=list[AssignmentResponse])
def get_rep_assignments(
    rep_id: str = Query(...),
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> list[Assignment]:
    if actor.user_id and actor.role == "rep" and actor.user_id != rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own assignments")

    rep_user = _get_user_or_404(db, rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)

    return db.scalars(select(Assignment).where(Assignment.rep_id == rep_id).order_by(Assignment.created_at.desc())).all()


@router.post("/sessions", response_model=SessionResponse)
def create_session(
    payload: SessionCreateRequest,
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> DrillSession:
    rep_user = _get_user_or_404(db, payload.rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)

    if actor.user_id and actor.role == "rep" and actor.user_id != payload.rep_id:
        raise HTTPException(status_code=403, detail="rep can only start their own session")

    assignment = db.scalar(select(Assignment).where(Assignment.id == payload.assignment_id))
    if assignment is None:
        raise HTTPException(status_code=404, detail="assignment not found")

    if assignment.rep_id != payload.rep_id:
        raise HTTPException(status_code=400, detail="assignment does not belong to rep")

    if assignment.scenario_id != payload.scenario_id:
        raise HTTPException(status_code=400, detail="session scenario must match assignment scenario")

    session = DrillSession(
        assignment_id=payload.assignment_id,
        rep_id=payload.rep_id,
        scenario_id=payload.scenario_id,
        prompt_version=(
            db.scalar(
                select(PromptVersion.version).where(
                    PromptVersion.prompt_type == "conversation",
                    PromptVersion.active.is_(True),
                )
            )
            or "conversation_v1"
        ),
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

    rep_user = _get_user_or_404(db, session.rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)

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


@router.get("/sessions")
def list_rep_sessions(
    rep_id: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "rep" and actor.user_id != rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own sessions")

    rep_user = _get_user_or_404(db, rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)

    rows = (
        db.execute(
            select(DrillSession, Scorecard)
            .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(DrillSession.rep_id == rep_id)
            .order_by(DrillSession.started_at.desc())
            .limit(limit)
        )
        .all()
    )
    return {
        "items": [
            {
                "session_id": session.id,
                "assignment_id": session.assignment_id,
                "scenario_id": session.scenario_id,
                "status": session.status.value,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "overall_score": scorecard.overall_score if scorecard else None,
            }
            for session, scorecard in rows
        ]
    }


@router.get("/progress")
def get_rep_progress(
    rep_id: str = Query(...),
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "rep" and actor.user_id != rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own progress")

    rep_user = _get_user_or_404(db, rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)

    sessions_count = db.scalar(select(func.count(DrillSession.id)).where(DrillSession.rep_id == rep_id)) or 0
    scored_count = (
        db.scalar(
            select(func.count(Scorecard.id)).join(DrillSession, DrillSession.id == Scorecard.session_id).where(DrillSession.rep_id == rep_id)
        )
        or 0
    )
    avg_score = db.scalar(
        select(func.avg(Scorecard.overall_score)).join(DrillSession, DrillSession.id == Scorecard.session_id).where(DrillSession.rep_id == rep_id)
    )
    return {
        "rep_id": rep_id,
        "session_count": int(sessions_count),
        "scored_session_count": int(scored_count),
        "average_score": round(float(avg_score), 2) if avg_score is not None else None,
    }


@router.post("/device-tokens", response_model=DeviceTokenResponse)
def register_device_token(
    payload: DeviceTokenCreateRequest,
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated actor required")
    user = _get_user_or_404(db, actor.user_id, "user")
    _ensure_same_org(actor, user.org_id)
    token = notification_service.register_device_token(
        db,
        user_id=user.id,
        platform=payload.platform,
        token=payload.token,
    )
    return {
        "id": token.id,
        "user_id": token.user_id,
        "platform": token.platform,
        "token": token.token,
        "status": token.status,
        "last_seen_at": token.last_seen_at,
    }


@router.delete("/device-tokens/{token_id}")
def revoke_device_token(
    token_id: str,
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated actor required")
    user = _get_user_or_404(db, actor.user_id, "user")
    _ensure_same_org(actor, user.org_id)
    revoked = notification_service.revoke_device_token(db, user_id=user.id, token_id=token_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="device token not found")
    return {"ok": True, "token_id": token_id}
