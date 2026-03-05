from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_manager
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact, SessionTurn
from app.models.types import ReviewReason, UserRole
from app.models.user import User
from app.schemas.assignment import AssignmentCreateRequest, AssignmentResponse, FollowupAssignmentRequest
from app.schemas.scorecard import ManagerReviewResponse, ScorecardOverrideRequest
from app.schemas.session import ManagerFeedResponse, SessionReplayResponse
from app.services.manager_action_service import ManagerActionService
from app.services.manager_feed_service import ManagerFeedService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/manager", tags=["manager"])
feed_service = ManagerFeedService()
storage_service = StorageService()
action_service = ManagerActionService()


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
    for artifact in artifacts:
        total_audio_duration_ms += int(artifact.metadata_json.get("duration_ms", 0))
        total_audio_frames += int(artifact.metadata_json.get("frame_count", 0))

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
        stage_timeline=stage_timeline,
        transport_metrics={
            "audio_duration_ms": total_audio_duration_ms,
            "audio_frame_count": total_audio_frames,
            "turn_count": len(transcript_turns),
            "objection_turn_count": len(objection_timeline),
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
