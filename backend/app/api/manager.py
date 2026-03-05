from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_manager
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact, SessionEvent, SessionTurn
from app.models.types import AssignmentStatus, ReviewReason, SessionStatus, UserRole
from app.models.user import Team, User
from app.schemas.assignment import AssignmentCreateRequest, AssignmentResponse, FollowupAssignmentRequest
from app.schemas.notification import NotificationDeliveryResponse
from app.schemas.scorecard import ManagerReviewResponse, ScorecardOverrideRequest
from app.schemas.session import ManagerFeedResponse, SessionReplayResponse
from app.services.manager_action_service import ManagerActionService
from app.services.manager_feed_service import ManagerFeedService
from app.services.notification_service import NotificationService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/manager", tags=["manager"])
feed_service = ManagerFeedService()
storage_service = StorageService()
action_service = ManagerActionService()
notification_service = NotificationService()


def _get_user_or_404(db: Session, user_id: str, label: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return user


def _ensure_same_org(actor: Actor, org_id: str | None) -> None:
    if actor.org_id and org_id and actor.org_id != org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")


def _get_scenario_or_404(db: Session, scenario_id: str) -> Scenario:
    scenario = db.scalar(select(Scenario).where(Scenario.id == scenario_id))
    if scenario is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return scenario


@router.get("/team")
def get_manager_team(
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own team")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    team = db.scalar(select(Team).where(Team.id == manager.team_id)) if manager.team_id else None
    if team is None:
        return {"manager_id": manager_id, "team_id": None, "items": []}

    reps = db.scalars(
        select(User).where(User.team_id == team.id, User.role == UserRole.REP).order_by(User.created_at.desc())
    ).all()
    return {
        "manager_id": manager_id,
        "team_id": team.id,
        "team_name": team.name,
        "items": [
            {
                "id": rep.id,
                "name": rep.name,
                "email": rep.email,
                "team_id": rep.team_id,
                "org_id": rep.org_id,
                "created_at": rep.created_at.isoformat() if rep.created_at else None,
            }
            for rep in reps
        ],
    }


@router.get("/assignments")
def list_manager_assignments(
    manager_id: str = Query(...),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own assignments")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    stmt = select(Assignment).where(Assignment.assigned_by == manager_id).order_by(Assignment.created_at.desc()).limit(limit)
    if status:
        try:
            stmt = stmt.where(Assignment.status == AssignmentStatus(status))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid assignment status") from exc

    items = db.scalars(stmt).all()
    return {
        "items": [
            {
                "id": assignment.id,
                "scenario_id": assignment.scenario_id,
                "rep_id": assignment.rep_id,
                "assigned_by": assignment.assigned_by,
                "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
                "status": assignment.status.value,
                "min_score_target": assignment.min_score_target,
                "retry_policy": assignment.retry_policy,
                "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
            }
            for assignment in items
        ]
    }


@router.get("/sessions")
def list_manager_sessions(
    manager_id: str = Query(...),
    rep_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own sessions")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    stmt = (
        select(DrillSession, Assignment, Scorecard)
        .join(Assignment, Assignment.id == DrillSession.assignment_id)
        .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
        .where(Assignment.assigned_by == manager_id)
        .order_by(DrillSession.started_at.desc())
        .limit(limit)
    )
    if rep_id:
        stmt = stmt.where(DrillSession.rep_id == rep_id)
    if status:
        try:
            stmt = stmt.where(DrillSession.status == SessionStatus(status))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid session status") from exc

    rows = db.execute(stmt).all()
    return {
        "items": [
            {
                "session_id": session.id,
                "assignment_id": assignment.id,
                "rep_id": session.rep_id,
                "scenario_id": session.scenario_id,
                "status": session.status.value,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "overall_score": scorecard.overall_score if scorecard else None,
            }
            for session, assignment, scorecard in rows
        ]
    }


@router.get("/sessions/{session_id}")
def get_manager_session_detail(
    session_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    rep = _get_user_or_404(db, session.rep_id, "rep")
    _ensure_same_org(actor, rep.org_id)
    assignment = db.scalar(select(Assignment).where(Assignment.id == session.assignment_id))
    scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))

    return {
        "session": {
            "id": session.id,
            "assignment_id": session.assignment_id,
            "rep_id": session.rep_id,
            "scenario_id": session.scenario_id,
            "status": session.status.value,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "duration_seconds": session.duration_seconds,
        },
        "assignment": (
            {
                "id": assignment.id,
                "status": assignment.status.value,
                "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
                "min_score_target": assignment.min_score_target,
                "retry_policy": assignment.retry_policy,
            }
            if assignment
            else None
        ),
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


@router.get("/sessions/{session_id}/audio")
def get_manager_session_audio(
    session_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    rep = _get_user_or_404(db, session.rep_id, "rep")
    _ensure_same_org(actor, rep.org_id)

    artifact = db.scalar(
        select(SessionArtifact)
        .where(SessionArtifact.session_id == session_id, SessionArtifact.artifact_type == "audio")
        .order_by(SessionArtifact.created_at.desc())
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="audio artifact not found")

    return {
        "session_id": session_id,
        "artifact_id": artifact.id,
        "storage_key": artifact.storage_key,
        "url": storage_service.get_presigned_url(artifact.storage_key),
        "metadata": artifact.metadata_json,
    }


@router.post("/assignments", response_model=AssignmentResponse)
def create_assignment(
    payload: AssignmentCreateRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> Assignment:
    if actor.user_id and actor.role == "manager" and actor.user_id != payload.assigned_by:
        raise HTTPException(status_code=403, detail="manager can only assign as themselves")

    manager = _get_user_or_404(db, payload.assigned_by, "assigning manager")
    rep = _get_user_or_404(db, payload.rep_id, "rep")
    scenario = _get_scenario_or_404(db, payload.scenario_id)

    if manager.role not in {UserRole.MANAGER, UserRole.ADMIN}:
        raise HTTPException(status_code=400, detail="assigned_by must be a manager/admin user")

    _ensure_same_org(actor, manager.org_id)
    _ensure_same_org(actor, rep.org_id)
    if manager.org_id != rep.org_id:
        raise HTTPException(status_code=400, detail="manager and rep must be in same organization")

    if scenario.org_id and scenario.org_id != manager.org_id:
        raise HTTPException(status_code=400, detail="scenario belongs to a different organization")

    if scenario.org_id is None:
        scenario.org_id = manager.org_id

    assignment = Assignment(
        scenario_id=payload.scenario_id,
        rep_id=payload.rep_id,
        assigned_by=payload.assigned_by,
        due_at=payload.due_at,
        min_score_target=payload.min_score_target,
        retry_policy=payload.retry_policy,
    )
    db.add(assignment)
    db.flush()

    action_service.log(
        db,
        manager_id=manager.id,
        action_type="assignment.created",
        target_type="assignment",
        target_id=assignment.id,
        summary="Manager assigned roleplay to rep",
        payload={
            "rep_id": rep.id,
            "scenario_id": scenario.id,
            "min_score_target": payload.min_score_target,
        },
    )

    db.commit()
    db.refresh(assignment)
    return assignment


@router.post("/scorecards/{scorecard_id}/followup-assignment")
def create_followup_assignment(
    scorecard_id: str,
    payload: FollowupAssignmentRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != payload.assigned_by:
        raise HTTPException(status_code=403, detail="manager can only assign as themselves")

    manager = _get_user_or_404(db, payload.assigned_by, "assigning manager")
    _ensure_same_org(actor, manager.org_id)

    scorecard = db.scalar(select(Scorecard).where(Scorecard.id == scorecard_id))
    if scorecard is None:
        raise HTTPException(status_code=404, detail="scorecard not found")

    session = db.scalar(select(DrillSession).where(DrillSession.id == scorecard.session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="source session not found")

    rep = _get_user_or_404(db, session.rep_id, "rep")
    if rep.org_id != manager.org_id:
        raise HTTPException(status_code=403, detail="cannot assign follow-up across organizations")

    scenario = _get_scenario_or_404(db, payload.scenario_id)
    if scenario.org_id and scenario.org_id != manager.org_id:
        raise HTTPException(status_code=400, detail="scenario belongs to a different organization")
    if scenario.org_id is None:
        scenario.org_id = manager.org_id

    followup_policy = {
        **payload.retry_policy,
        "source_scorecard_id": scorecard.id,
        "weakness_tags": scorecard.weakness_tags,
    }
    assignment = Assignment(
        scenario_id=payload.scenario_id,
        rep_id=session.rep_id,
        assigned_by=payload.assigned_by,
        due_at=payload.due_at,
        min_score_target=payload.min_score_target,
        retry_policy=followup_policy,
    )
    db.add(assignment)
    db.flush()

    action_service.log(
        db,
        manager_id=manager.id,
        action_type="assignment.followup_created",
        target_type="assignment",
        target_id=assignment.id,
        summary="Manager created follow-up assignment from scorecard",
        payload={
            "source_scorecard_id": scorecard.id,
            "weakness_tags": scorecard.weakness_tags,
            "scenario_id": scenario.id,
            "rep_id": rep.id,
        },
    )

    db.commit()
    db.refresh(assignment)

    return {
        "assignment": AssignmentResponse.model_validate(assignment).model_dump(),
        "source_scorecard_id": scorecard.id,
        "weakness_tags": scorecard.weakness_tags,
    }


@router.get("/feed", response_model=ManagerFeedResponse)
def get_manager_feed(
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> ManagerFeedResponse:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own feed")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    items = feed_service.get_feed(db, manager_id=manager_id)
    return ManagerFeedResponse(items=items)


@router.get("/reps/{rep_id}/progress")
def get_rep_progress(
    rep_id: str,
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own rep progress")

    manager = _get_user_or_404(db, manager_id, "manager")
    rep = _get_user_or_404(db, rep_id, "rep")
    _ensure_same_org(actor, manager.org_id)
    if manager.org_id != rep.org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")

    stmt = (
        select(
            DrillSession.id.label("session_id"),
            DrillSession.started_at.label("started_at"),
            DrillSession.status.label("status"),
            Scorecard.overall_score.label("overall_score"),
        )
        .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
        .where(DrillSession.rep_id == rep_id)
        .order_by(DrillSession.started_at.desc())
        .limit(100)
    )
    rows = db.execute(stmt).mappings().all()
    scores = [float(row["overall_score"]) for row in rows if row["overall_score"] is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    return {
        "rep_id": rep_id,
        "session_count": len(rows),
        "scored_session_count": len(scores),
        "average_score": avg_score,
        "latest_sessions": [
            {
                "session_id": row["session_id"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "status": row["status"].value if row["status"] else None,
                "overall_score": row["overall_score"],
            }
            for row in rows[:20]
        ],
    }


@router.get("/analytics")
def get_manager_analytics(
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    assignment_count = db.scalar(select(func.count(Assignment.id)).where(Assignment.assigned_by == manager_id)) or 0
    completed_assignments = (
        db.scalar(
            select(func.count(Assignment.id)).where(
                Assignment.assigned_by == manager_id, Assignment.status == AssignmentStatus.COMPLETED
            )
        )
        or 0
    )
    sessions_count = (
        db.scalar(
            select(func.count(DrillSession.id))
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .where(Assignment.assigned_by == manager_id)
        )
        or 0
    )
    avg_score = db.scalar(
        select(func.avg(Scorecard.overall_score))
        .join(DrillSession, DrillSession.id == Scorecard.session_id)
        .join(Assignment, Assignment.id == DrillSession.assignment_id)
        .where(Assignment.assigned_by == manager_id)
    )

    unique_reps = db.scalar(select(func.count(func.distinct(Assignment.rep_id))).where(Assignment.assigned_by == manager_id)) or 0

    return {
        "manager_id": manager_id,
        "assignment_count": int(assignment_count),
        "completed_assignment_count": int(completed_assignments),
        "sessions_count": int(sessions_count),
        "active_rep_count": int(unique_reps),
        "average_score": round(float(avg_score), 2) if avg_score is not None else None,
        "completion_rate": round((completed_assignments / assignment_count), 3) if assignment_count else 0.0,
    }


@router.get("/sessions/{session_id}/replay", response_model=SessionReplayResponse)
def get_session_replay(
    session_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> SessionReplayResponse:
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    rep = _get_user_or_404(db, session.rep_id, "rep")
    _ensure_same_org(actor, rep.org_id)

    turns = db.scalars(select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())).all()
    scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
    artifacts = db.scalars(
        select(SessionArtifact).where(SessionArtifact.session_id == session_id, SessionArtifact.artifact_type == "audio")
    ).all()
    state_events = db.scalars(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id, SessionEvent.event_type == "server.session.state")
        .order_by(SessionEvent.event_ts.asc())
    ).all()

    transcript_turns = [
        {
            "turn_id": t.id,
            "turn_index": t.turn_index,
            "speaker": t.speaker.value,
            "stage": t.stage,
            "text": t.text,
            "started_at": t.started_at.isoformat(),
            "ended_at": t.ended_at.isoformat(),
        }
        for t in turns
    ]
    objection_timeline = [
        {"turn_id": t.id, "turn_index": t.turn_index, "objection_tags": t.objection_tags}
        for t in turns
        if t.objection_tags
    ]

    stage_timeline: list[dict] = []
    last_stage = None
    for turn in turns:
        if turn.stage != last_stage:
            stage_timeline.append(
                {
                    "stage": turn.stage,
                    "entered_at": turn.started_at.isoformat(),
                    "turn_index": turn.turn_index,
                    "speaker": turn.speaker.value,
                }
            )
            last_stage = turn.stage

    total_audio_duration_ms = 0
    total_audio_frames = 0
    total_barge_ins = 0
    for artifact in artifacts:
        total_audio_duration_ms += int(artifact.metadata_json.get("duration_ms", 0))
        total_audio_frames += int(artifact.metadata_json.get("frame_count", 0))
        total_barge_ins += int(artifact.metadata_json.get("barge_in_count", 0))

    interruption_timeline = []
    for event in state_events:
        if event.payload.get("state") != "barge_in_detected":
            continue
        interruption_timeline.append(
            {
                "event_id": event.event_id,
                "at": event.payload.get("at", event.event_ts.isoformat()),
                "reason": event.payload.get("reason", "unknown"),
                "latency_ms": int(event.payload.get("latency_ms", 0)),
                "sequence": event.sequence,
            }
        )

    return SessionReplayResponse(
        session_id=session.id,
        status=session.status.value,
        audio_artifacts=[
            {
                "artifact_id": a.id,
                "storage_key": a.storage_key,
                "url": storage_service.get_presigned_url(a.storage_key),
                "metadata": a.metadata_json,
            }
            for a in artifacts
        ],
        transcript_turns=transcript_turns,
        objection_timeline=objection_timeline,
        interruption_timeline=interruption_timeline,
        stage_timeline=stage_timeline,
        transport_metrics={
            "audio_duration_ms": total_audio_duration_ms,
            "audio_frame_count": total_audio_frames,
            "turn_count": len(transcript_turns),
            "objection_turn_count": len(objection_timeline),
            "barge_in_count": max(total_barge_ins, len(interruption_timeline)),
        },
        scorecard=(
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
    )


@router.patch("/scorecards/{scorecard_id}", response_model=ManagerReviewResponse)
def override_scorecard(
    scorecard_id: str,
    payload: ScorecardOverrideRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> ManagerReview:
    if actor.user_id and actor.role == "manager" and actor.user_id != payload.reviewer_id:
        raise HTTPException(status_code=403, detail="manager can only review as themselves")

    reviewer = _get_user_or_404(db, payload.reviewer_id, "reviewer")
    _ensure_same_org(actor, reviewer.org_id)

    scorecard = db.scalar(select(Scorecard).where(Scorecard.id == scorecard_id))
    if scorecard is None:
        raise HTTPException(status_code=404, detail="scorecard not found")

    source_session = db.scalar(select(DrillSession).where(DrillSession.id == scorecard.session_id))
    if source_session is None:
        raise HTTPException(status_code=404, detail="source session not found")

    rep = _get_user_or_404(db, source_session.rep_id, "rep")
    if rep.org_id != reviewer.org_id:
        raise HTTPException(status_code=403, detail="cannot review scorecards across organizations")

    if payload.reason_code not in {reason.value for reason in ReviewReason}:
        raise HTTPException(status_code=400, detail="invalid reason_code")

    review = ManagerReview(
        scorecard_id=scorecard_id,
        reviewer_id=payload.reviewer_id,
        reviewed_at=datetime.now(timezone.utc),
        reason_code=ReviewReason(payload.reason_code),
        override_score=payload.override_score,
        notes=payload.notes,
    )
    db.add(review)
    db.flush()

    action_service.log(
        db,
        manager_id=reviewer.id,
        action_type="scorecard.reviewed",
        target_type="scorecard",
        target_id=scorecard.id,
        summary="Manager reviewed or overrode scorecard",
        payload={
            "reason_code": payload.reason_code,
            "override_score": payload.override_score,
            "has_notes": bool(payload.notes),
        },
    )

    db.commit()
    db.refresh(review)
    return review


@router.get("/actions")
def get_manager_actions(
    manager_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own actions")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    logs = action_service.recent(db, manager_id=manager_id, limit=limit)
    return {
        "items": [
            {
                "id": log.id,
                "manager_id": log.manager_id,
                "action_type": log.action_type,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "summary": log.summary,
                "payload": log.payload,
                "occurred_at": log.occurred_at.isoformat(),
            }
            for log in logs
        ]
    }


@router.get("/notifications")
def get_manager_notifications(
    manager_id: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own notifications")
    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    rows = notification_service.list_manager_notifications(db, manager_id=manager_id, limit=limit)
    items = [
        NotificationDeliveryResponse(
            id=row.id,
            session_id=row.session_id,
            manager_id=row.manager_id,
            channel=row.channel,
            payload=row.payload,
            provider_response=row.provider_response,
            status=row.status,
            retries=row.retries,
            next_retry_at=row.next_retry_at,
            last_error=row.last_error,
            sent_at=row.sent_at,
            created_at=row.created_at,
        ).model_dump()
        for row in rows
    ]
    return {"items": items}
