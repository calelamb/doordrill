import os
import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_rep_or_manager
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus
from app.models.user import User, Team
from app.schemas.assignment import AssignmentResponse
from app.schemas.notification import DeviceTokenCreateRequest, DeviceTokenResponse
from app.schemas.profile import ProfileUpdateRequest, HierarchyNode
from app.schemas.session import SessionCreateRequest, SessionResponse
from app.services.notification_service import NotificationService
from app.services.manager_review_service import ManagerReviewService

router = APIRouter(prefix="/rep", tags=["rep"])
notification_service = NotificationService()
review_service = ManagerReviewService()


def _get_user_or_404(db: Session, user_id: str, label: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return user


def _ensure_same_org(actor: Actor, org_id: str | None) -> None:
    if actor.org_id and org_id and actor.org_id != org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")


@router.get("/lookup")
def lookup_rep_by_email(email: str = Query(...), db: Session = Depends(get_db)) -> dict:
    # Development only endpoint to lookup a rep by email without auth
    user = db.scalar(select(User).where(User.email == email.lower(), User.role == "rep"))
    if not user:
        # If user doesn't exist, create a mock user for them automatically for testing purposes
        from app.models.user import Organization
        from app.models.types import UserRole
        # Find any organization to attach them to, or create one
        org = db.scalar(select(Organization).limit(1))
        if not org:
            org = Organization(name="Test Org", industry="Solar", plan_tier="starter")
            db.add(org)
            db.flush()
            
        user = User(
            org_id=org.id,
            role=UserRole.REP,
            name=email.split("@")[0].replace(".", " ").title(),
            email=email.lower(),
            password_hash="mock",
            auth_provider="local",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
    return {"rep_id": user.id}


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

    if payload.assignment_id:
        assignment = db.scalar(select(Assignment).where(Assignment.id == payload.assignment_id))
        if assignment is None:
            raise HTTPException(status_code=404, detail="assignment not found")

        if assignment.rep_id != payload.rep_id:
            raise HTTPException(status_code=400, detail="assignment does not belong to rep")

        if assignment.scenario_id != payload.scenario_id:
            raise HTTPException(status_code=400, detail="session scenario must match assignment scenario")
    else:
        # Auto-create a practice assignment
        assignment = Assignment(
            scenario_id=payload.scenario_id,
            rep_id=payload.rep_id,
            assigned_by=payload.rep_id,
            status=AssignmentStatus.ASSIGNED,
        )
        db.add(assignment)
        db.flush()

    session = DrillSession(
        assignment_id=assignment.id,
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
    manager_coaching_note = review_service.latest_rep_visible_note(db, session_id=session_id)
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
        "manager_coaching_note": (
            {
                "id": manager_coaching_note.id,
                "scorecard_id": manager_coaching_note.scorecard_id,
                "reviewer_id": manager_coaching_note.reviewer_id,
                "note": manager_coaching_note.note,
                "visible_to_rep": manager_coaching_note.visible_to_rep,
                "weakness_tags": manager_coaching_note.weakness_tags,
                "created_at": manager_coaching_note.created_at.isoformat() if manager_coaching_note.created_at else None,
            }
            if manager_coaching_note
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
        "rep_name": rep_user.name,
        "rep_email": rep_user.email,
        "rep_avatar_url": getattr(rep_user, "avatar_url", None),
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
        "provider": token.provider,
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

@router.post("/profile/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db)
) -> dict:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated actor required")
    user = _get_user_or_404(db, actor.user_id, "user")
    
    ext = file.filename.split(".")[-1] if file.filename else "jpg"
    filename = f"{user.id}_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join("uploads", "avatars", filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    user.avatar_url = f"/uploads/avatars/{filename}"
    db.commit()
    
    return {"avatar_url": user.avatar_url}

@router.patch("/profile")
def update_profile(
    payload: ProfileUpdateRequest,
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db)
) -> dict:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated actor required")
    user = _get_user_or_404(db, actor.user_id, "user")
    
    if payload.name is not None:
        user.name = payload.name
        
    db.commit()
    return {"name": user.name, "avatar_url": user.avatar_url}

@router.get("/hierarchy", response_model=list[HierarchyNode])
def get_hierarchy(
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db)
) -> list[HierarchyNode]:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated actor required")
    
    # Start from the current user and go up
    current_user = _get_user_or_404(db, actor.user_id, "user")
    
    chain = []
    
    # Add the user themselves
    chain.append(HierarchyNode(
        id=current_user.id,
        name=current_user.name,
        role=current_user.role,
        avatar_url=current_user.avatar_url
    ))
    
    # If the user is on a team, find their manager
    if current_user.team_id:
        team = db.scalar(select(Team).where(Team.id == current_user.team_id))
        if team and team.manager_id:
            manager = db.scalar(select(User).where(User.id == team.manager_id))
            if manager:
                chain.insert(0, HierarchyNode(
                    id=manager.id,
                    name=manager.name,
                    role=manager.role,
                    avatar_url=manager.avatar_url
                ))
                
                # If manager is also on a team, get the director
                if manager.team_id:
                    manager_team = db.scalar(select(Team).where(Team.id == manager.team_id))
                    if manager_team and manager_team.manager_id and manager_team.manager_id != manager.id:
                        director = db.scalar(select(User).where(User.id == manager_team.manager_id))
                        if director:
                            chain.insert(0, HierarchyNode(
                                id=director.id,
                                name=director.name,
                                role=director.role,
                                avatar_url=director.avatar_url
                            ))
                            
    return chain
