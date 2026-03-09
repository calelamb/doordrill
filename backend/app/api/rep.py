import os
import shutil
import uuid
from typing import Any
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_rep_or_manager
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.prompt_version import PromptVersion
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.types import AssignmentStatus, SessionStatus
from app.models.user import User, Team
from app.schemas.adaptive_training import RepAdaptivePlanResponse, RepForecastResponse
from app.schemas.assignment import AssignmentResponse
from app.schemas.notification import DeviceTokenCreateRequest, DeviceTokenResponse
from app.schemas.profile import ProfileUpdateRequest, HierarchyNode
from app.schemas.scorecard import CategoryScoreV2, ManagerCoachingNoteResponse
from app.schemas.session import (
    RepProgressResponse,
    RepProgressTrendResponse,
    RepSessionFeedbackResponse,
    SessionCreateRequest,
    SessionResponse,
)
from app.services.adaptive_training_service import AdaptiveTrainingService
from app.services.notification_service import NotificationService
from app.services.manager_review_service import ManagerReviewService
from app.services.predictive_modeling_service import PredictiveModelingService

router = APIRouter(prefix="/rep", tags=["rep"])
REP_CATEGORY_KEY_MAP = {
    "opening": "opening",
    "pitch": "pitch_delivery",
    "pitch_delivery": "pitch_delivery",
    "objection_handling": "objection_handling",
    "closing": "closing_technique",
    "closing_technique": "closing_technique",
    "professionalism": "professionalism",
}
REP_CATEGORY_ORDER = (
    "opening",
    "pitch_delivery",
    "objection_handling",
    "closing_technique",
    "professionalism",
)
IMPROVEMENT_TARGET_LABELS = {
    "opening": "Opening",
    "pitch_delivery": "Pitch",
    "objection_handling": "Objection Handling",
    "closing_technique": "Closing",
    "professionalism": "Professionalism",
}
REP_PROGRESS_TIMEZONE = ZoneInfo("America/Denver")
notification_service = NotificationService()
review_service = ManagerReviewService()
predictive_modeling_service = PredictiveModelingService()
adaptive_training_service = AdaptiveTrainingService()


def _get_user_or_404(db: Session, user_id: str, label: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return user


def _ensure_same_org(actor: Actor, org_id: str | None) -> None:
    if actor.org_id and org_id and actor.org_id != org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")


def _category_score_value(raw_value: Any) -> float | None:
    value = raw_value.get("score") if isinstance(raw_value, dict) else raw_value
    if not isinstance(value, (int, float)):
        return None
    return round(float(value), 2)


def _normalize_category_scores(category_scores: dict[str, Any] | None) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_key, value in (category_scores or {}).items():
        category_key = REP_CATEGORY_KEY_MAP.get(str(raw_key))
        if not category_key or category_key in normalized:
            continue
        score = _category_score_value(value)
        if score is None:
            continue
        normalized[category_key] = score
    return normalized


def _linear_regression_slope(scores: list[float]) -> float | None:
    if len(scores) < 2:
        return None
    x_mean = (len(scores) - 1) / 2
    y_mean = sum(scores) / len(scores)
    numerator = sum((index - x_mean) * (score - y_mean) for index, score in enumerate(scores))
    denominator = sum((index - x_mean) ** 2 for index in range(len(scores)))
    if denominator <= 0:
        return None
    return numerator / denominator


def _session_completed_at(session: DrillSession) -> datetime | None:
    completed_at = session.ended_at or session.started_at or getattr(session, "created_at", None)
    if completed_at is None:
        return None
    if completed_at.tzinfo is None:
        return completed_at.replace(tzinfo=timezone.utc)
    return completed_at.astimezone(timezone.utc)


def _session_local_date(session: DrillSession) -> date | None:
    completed_at = _session_completed_at(session)
    if completed_at is None:
        return None
    return completed_at.astimezone(REP_PROGRESS_TIMEZONE).date()


def _calculate_streak_days(scored_sessions: list[DrillSession]) -> int:
    completed_days = {local_date for session in scored_sessions if (local_date := _session_local_date(session)) is not None}
    if not completed_days:
        return 0

    today_local = datetime.now(timezone.utc).astimezone(REP_PROGRESS_TIMEZONE).date()
    if today_local not in completed_days:
        return 0

    streak_days = 0
    cursor = today_local
    while cursor in completed_days:
        streak_days += 1
        cursor -= timedelta(days=1)
    return streak_days


def _calculate_most_improved_category(scored_rows: list[tuple[DrillSession, Scorecard]]) -> tuple[str | None, float | None]:
    if len(scored_rows) < 6:
        return None, None

    first_window = scored_rows[:3]
    last_window = scored_rows[-3:]
    best_category: str | None = None
    best_delta = 0.0

    for category_key in REP_CATEGORY_ORDER:
        first_values = [
            normalized[category_key]
            for _, scorecard in first_window
            if category_key in (normalized := _normalize_category_scores(scorecard.category_scores))
        ]
        last_values = [
            normalized[category_key]
            for _, scorecard in last_window
            if category_key in (normalized := _normalize_category_scores(scorecard.category_scores))
        ]

        if not first_values or not last_values:
            continue

        delta = (sum(last_values) / len(last_values)) - (sum(first_values) / len(first_values))
        if delta > best_delta:
            best_category = category_key
            best_delta = delta

    if best_category is None or best_delta <= 0:
        return None, None

    return best_category, round(best_delta, 2)


def _serialize_transcript(turns: list[SessionTurn]) -> list[dict[str, Any]]:
    return [
        {
            "turn_index": turn.turn_index,
            "rep_text": turn.text if turn.speaker.value == "rep" else "",
            "ai_text": turn.text if turn.speaker.value == "ai" else "",
            "turn_id": turn.id,
            "objection_tags": list(turn.objection_tags or []),
            "emotion": turn.emotion_after or turn.emotion_before,
            "stage": turn.stage,
        }
        for turn in turns
    ]


def _build_improvement_targets(category_scores: dict[str, CategoryScoreV2]) -> list[dict[str, Any]]:
    candidates = [
        {
            "category": category_key,
            "label": IMPROVEMENT_TARGET_LABELS.get(category_key, category_key.replace("_", " ").title()),
            "target": category.improvement_target,
            "score": round(float(category.score), 2),
        }
        for category_key, category in category_scores.items()
        if category.improvement_target
    ]
    return sorted(candidates, key=lambda item: (item["score"], item["label"]))[:3]


def _serialize_scorecard(scorecard: Scorecard | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if scorecard is None:
        return None, []

    schema_version = scorecard.scorecard_schema_version or "v1"
    serialized_category_scores: dict[str, Any]
    improvement_targets: list[dict[str, Any]] = []

    if schema_version == "v2":
        serialized_category_scores = {}
        parsed_category_scores: dict[str, CategoryScoreV2] = {}
        for category_key, raw_value in (scorecard.category_scores or {}).items():
            try:
                parsed = CategoryScoreV2.model_validate(raw_value)
            except ValidationError:
                serialized_category_scores[category_key] = raw_value
                continue
            parsed_category_scores[category_key] = parsed
            serialized_category_scores[category_key] = parsed.model_dump()
        improvement_targets = _build_improvement_targets(parsed_category_scores)
    else:
        serialized_category_scores = scorecard.category_scores or {}

    return (
        {
            "id": scorecard.id,
            "overall_score": scorecard.overall_score,
            "scorecard_schema_version": schema_version,
            "category_scores": serialized_category_scores,
            "highlights": scorecard.highlights,
            "ai_summary": scorecard.ai_summary,
            "evidence_turn_ids": scorecard.evidence_turn_ids,
            "weakness_tags": scorecard.weakness_tags,
        },
        improvement_targets,
    )


def _default_rep_plan() -> dict[str, Any]:
    return {
        "focus_skills": [],
        "recommended_difficulty": 1,
        "readiness_trajectory": {},
        "next_scenario_suggestion": None,
    }


def _scenario_focus_skills(scenario: Scenario) -> list[str]:
    focus = adaptive_training_service._scenario_skill_focus(scenario)
    return [
        skill
        for skill, weight in sorted(focus.items(), key=lambda item: item[1], reverse=True)
        if weight >= 0.18
    ]


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


@router.get("/{rep_id}/forecast", response_model=RepForecastResponse)
def get_rep_forecast(
    rep_id: str,
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "rep" and actor.user_id != rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own forecast")

    rep_user = _get_user_or_404(db, rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)
    return predictive_modeling_service.get_rep_forecast(db, rep_id=rep_id)


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


@router.get("/sessions/{session_id}", response_model=RepSessionFeedbackResponse)
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
    transcript_turns = db.scalars(
        select(SessionTurn)
        .where(SessionTurn.session_id == session_id)
        .order_by(SessionTurn.turn_index.asc(), SessionTurn.started_at.asc())
    ).all()
    scorecard_payload, improvement_targets = _serialize_scorecard(scorecard)
    manager_coaching_note = review_service.latest_rep_visible_note(db, session_id=session_id)
    return {
        "session": SessionResponse.model_validate(session).model_dump(mode="json"),
        "scorecard": scorecard_payload,
        "manager_coaching_note": (
            ManagerCoachingNoteResponse.model_validate(manager_coaching_note).model_dump(mode="json")
            if manager_coaching_note
            else None
        ),
        "transcript": _serialize_transcript(transcript_turns),
        "improvement_targets": improvement_targets,
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


@router.get("/progress", response_model=RepProgressResponse)
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
    scored_rows = (
        db.execute(
            select(DrillSession, Scorecard)
            .join(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(DrillSession.rep_id == rep_id)
            .order_by(DrillSession.started_at.asc(), DrillSession.created_at.asc())
        )
        .all()
    )
    scored_sessions = [session for session, _ in scored_rows]
    scored_count = len(scored_rows)
    avg_score = (
        round(sum(float(scorecard.overall_score) for _, scorecard in scored_rows) / scored_count, 2)
        if scored_count > 0
        else None
    )
    best_row = (
        max(
            scored_rows,
            key=lambda row: (
                float(row[1].overall_score),
                (_session_completed_at(row[0]) or datetime.min.replace(tzinfo=timezone.utc)),
            ),
        )
        if scored_rows
        else None
    )
    last_scored_session_at = (
        max(
            (_session_completed_at(session) for session in scored_sessions if _session_completed_at(session) is not None),
            default=None,
        )
    )
    streak_days = _calculate_streak_days(scored_sessions)
    most_improved_category, most_improved_delta = _calculate_most_improved_category(scored_rows)

    return {
        "rep_id": rep_id,
        "rep_name": rep_user.name,
        "rep_email": rep_user.email,
        "rep_avatar_url": getattr(rep_user, "avatar_url", None),
        "session_count": int(sessions_count),
        "scored_session_count": int(scored_count),
        "completed_drills": int(scored_count),
        "average_score": avg_score,
        "streak_days": streak_days,
        "personal_best": round(float(best_row[1].overall_score), 2) if best_row else None,
        "personal_best_session_id": best_row[0].id if best_row else None,
        "most_improved_category": most_improved_category,
        "most_improved_delta": most_improved_delta,
        "last_scored_session_at": last_scored_session_at.isoformat() if last_scored_session_at else None,
    }


@router.get("/progress/trend", response_model=RepProgressTrendResponse)
def get_rep_progress_trend(
    rep_id: str = Query(...),
    sessions: int = Query(default=10, ge=1, le=20),
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "rep" and actor.user_id != rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own progress")

    rep_user = _get_user_or_404(db, rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)

    rows = (
        db.execute(
            select(DrillSession, Scorecard)
            .join(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(DrillSession.rep_id == rep_id)
            .order_by(DrillSession.started_at.desc(), DrillSession.created_at.desc())
            .limit(sessions)
        )
        .all()
    )

    ordered_rows = list(reversed(rows))
    session_items: list[dict[str, Any]] = []
    overall_scores: list[float] = []
    category_totals: dict[str, list[float]] = {key: [] for key in REP_CATEGORY_ORDER}

    for session, scorecard in ordered_rows:
        category_scores = _normalize_category_scores(scorecard.category_scores)
        for category_key, value in category_scores.items():
            category_totals.setdefault(category_key, []).append(value)
        overall_score = round(float(scorecard.overall_score), 2)
        overall_scores.append(overall_score)
        session_items.append(
            {
                "session_id": session.id,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "overall_score": overall_score,
                "category_scores": category_scores,
            }
        )

    slope = _linear_regression_slope(overall_scores)
    if slope is not None and slope > 0.2:
        overall_trend = "improving"
    elif slope is not None and slope < -0.2:
        overall_trend = "declining"
    else:
        overall_trend = "stable"

    return {
        "sessions": session_items,
        "category_averages": {
            category_key: round(sum(values) / len(values), 2)
            for category_key, values in category_totals.items()
            if values
        },
        "overall_trend": overall_trend,
    }


@router.get("/plan", response_model=RepAdaptivePlanResponse)
def get_rep_plan(
    rep_id: str = Query(...),
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "rep" and actor.user_id != rep_id:
        raise HTTPException(status_code=403, detail="rep can only access their own plan")

    rep_user = _get_user_or_404(db, rep_id, "rep")
    _ensure_same_org(actor, rep_user.org_id)

    try:
        plan = adaptive_training_service.build_plan(db, rep_id=rep_id)
    except Exception:
        return _default_rep_plan()

    if int(plan.get("session_count") or 0) <= 0:
        return _default_rep_plan()

    focus_skills = [
        str(skill)
        for skill in plan.get("weakest_skills", [])
        if isinstance(skill, str) and skill
    ]
    if not focus_skills:
        focus_skills = [
            str(skill)
            for skill in ((plan.get("recommended_scenarios") or [{}])[0].get("focus_skills") or [])
            if isinstance(skill, str) and skill
        ]

    recommended_difficulty = max(1, min(5, int(plan.get("recommended_difficulty") or 1)))
    readiness_trajectory = {
        str(item.get("skill")): {
            "sessions_to_readiness": item.get("sessions_to_readiness"),
            "slope": round(float(item.get("velocity") or 0.0), 4),
        }
        for item in (plan.get("readiness_forecast") or [])
        if isinstance(item, dict) and item.get("skill")
    }

    recommendations_by_id = {
        str(item.get("scenario_id")): item
        for item in (plan.get("recommended_scenarios") or [])
        if isinstance(item, dict) and item.get("scenario_id")
    }
    candidates = db.scalars(
        select(Scenario)
        .where(
            Scenario.difficulty == recommended_difficulty,
            or_(Scenario.org_id == rep_user.org_id, Scenario.org_id.is_(None)),
        )
        .order_by(Scenario.created_at.desc(), Scenario.name.asc())
    ).all()

    next_scenario_suggestion = None
    focus_skill_set = set(focus_skills)
    ranked_candidates: list[tuple[int, float, str, dict[str, Any]]] = []
    for scenario in candidates:
        recommendation = recommendations_by_id.get(scenario.id, {})
        scenario_focus_skills = [
            str(skill)
            for skill in (recommendation.get("focus_skills") or _scenario_focus_skills(scenario))
            if isinstance(skill, str) and skill
        ]
        overlap = len(focus_skill_set.intersection(scenario_focus_skills))
        if overlap <= 0:
            continue
        ranked_candidates.append(
            (
                overlap,
                float(recommendation.get("recommendation_score") or 0.0),
                scenario.name.lower(),
                {
                    "name": scenario.name,
                    "scenario_id": scenario.id,
                    "difficulty": int(scenario.difficulty),
                    "reason": recommendation.get("rationale")
                    or f"Targets {', '.join(scenario_focus_skills[:2]) or 'core selling fundamentals'}.",
                },
            )
        )

    if ranked_candidates:
        ranked_candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        next_scenario_suggestion = ranked_candidates[0][3]

    return {
        "focus_skills": focus_skills,
        "recommended_difficulty": recommended_difficulty,
        "readiness_trajectory": readiness_trajectory,
        "next_scenario_suggestion": next_scenario_suggestion,
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
