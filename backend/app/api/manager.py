from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.scorecard import ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact, SessionTurn
from app.models.types import ReviewReason
from app.schemas.assignment import AssignmentCreateRequest, AssignmentResponse
from app.schemas.scorecard import ManagerReviewResponse, ScorecardOverrideRequest
from app.schemas.session import ManagerFeedResponse, SessionReplayResponse
from app.services.manager_feed_service import ManagerFeedService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/manager", tags=["manager"])
feed_service = ManagerFeedService()
storage_service = StorageService()


@router.post("/assignments", response_model=AssignmentResponse)
def create_assignment(payload: AssignmentCreateRequest, db: Session = Depends(get_db)) -> Assignment:
    assignment = Assignment(
        scenario_id=payload.scenario_id,
        rep_id=payload.rep_id,
        assigned_by=payload.assigned_by,
        due_at=payload.due_at,
        min_score_target=payload.min_score_target,
        retry_policy=payload.retry_policy,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


@router.get("/feed", response_model=ManagerFeedResponse)
def get_manager_feed(manager_id: str = Query(...), db: Session = Depends(get_db)) -> ManagerFeedResponse:
    items = feed_service.get_feed(db, manager_id=manager_id)
    return ManagerFeedResponse(items=items)


@router.get("/sessions/{session_id}/replay", response_model=SessionReplayResponse)
def get_session_replay(session_id: str, db: Session = Depends(get_db)) -> SessionReplayResponse:
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

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
        scorecard=(
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
    )


@router.patch("/scorecards/{scorecard_id}", response_model=ManagerReviewResponse)
def override_scorecard(
    scorecard_id: str,
    payload: ScorecardOverrideRequest,
    db: Session = Depends(get_db),
) -> ManagerReview:
    scorecard = db.scalar(select(Scorecard).where(Scorecard.id == scorecard_id))
    if scorecard is None:
        raise HTTPException(status_code=404, detail="scorecard not found")

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
    db.commit()
    db.refresh(review)
    return review
