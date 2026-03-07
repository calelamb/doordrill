import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import json
from statistics import pstdev
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_manager, resolve_ws_actor_with_query
from app.db.session import get_db
from app.models.analytics import AnalyticsFactAlert, AnalyticsFactManagerCalibration
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.scenario import Scenario
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact, SessionEvent, SessionTurn
from app.models.types import AssignmentStatus, ReviewReason, SessionStatus, UserRole
from app.models.user import Team, User
from app.schemas.adaptive_training import (
    AdaptiveAssignmentRequest,
    AdaptiveAssignmentResponse,
    AdaptiveTrainingPlanResponse,
)
from app.schemas.assignment import AssignmentCreateRequest, AssignmentResponse, FollowupAssignmentRequest
from app.schemas.manager_analytics import CalibrationAnalyticsResponse, RepRiskDetailResponse
from app.schemas.notification import NotificationDeliveryResponse
from app.schemas.manager_ai import (
    ManagerChatRequest,
    ManagerChatResponse,
    RepInsightRequest,
    RepInsightResponse,
    SessionAnnotationRequest,
    SessionAnnotationsResponse,
    TeamCoachingSummaryRequest,
    TeamCoachingSummaryResponse,
)
from app.schemas.scorecard import (
    BulkReviewRequest,
    BulkReviewResponse,
    CoachingNoteCreateRequest,
    ManagerCoachingNoteResponse,
    ManagerReviewResponse,
    ScorecardOverrideRequest,
)
from app.schemas.session import (
    LiveSessionCard,
    LiveSessionsResponse,
    LiveSessionTranscriptResponse,
    ManagerFeedResponse,
    SessionReplayResponse,
)
from app.services.adaptive_training_service import AdaptiveTrainingService
from app.services.manager_action_service import DISAGREEMENT_THRESHOLD, ManagerActionService
from app.services.manager_ai_coaching_service import (
    AiCoachingDataUnavailableError,
    AiCoachingUnavailableError,
    ManagerAiCoachingService,
)
from app.services.analytics_refresh_service import AnalyticsRefreshService
from app.services.management_analytics_runtime_service import ManagementAnalyticsRuntimeService
from app.services.manager_feed_service import ManagerFeedService
from app.services.manager_review_service import ManagerReviewService
from app.services.notification_service import NotificationService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/manager", tags=["manager"])
adaptive_training_service = AdaptiveTrainingService()
feed_service = ManagerFeedService()
storage_service = StorageService()
action_service = ManagerActionService()
review_service = ManagerReviewService()
notification_service = NotificationService()
management_analytics_service = ManagementAnalyticsRuntimeService()
analytics_refresh_service = AnalyticsRefreshService()
manager_ai_service = ManagerAiCoachingService()
RUBRIC_CATEGORY_KEYS = {
    "opening": "opening",
    "pitch": "pitch",
    "pitch_delivery": "pitch",
    "objection_handling": "objection_handling",
    "closing": "closing",
    "closing_technique": "closing",
    "professionalism": "professionalism",
}
TEAM_RISK_CATEGORY_KEYS = ("opening", "pitch", "objection_handling", "closing", "professionalism")


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


def _serialize_review(review: ManagerReview) -> ManagerReviewResponse:
    return ManagerReviewResponse.model_validate(review)


def _serialize_coaching_note(note: ManagerCoachingNote) -> ManagerCoachingNoteResponse:
    return ManagerCoachingNoteResponse.model_validate(note)


def _resolve_period_bounds(
    *,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime, datetime, datetime, datetime]:
    now = datetime.now(timezone.utc)
    if date_to is None:
        date_to = now
    if date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)
    date_to = date_to.replace(microsecond=0)

    normalized_period = period.lower()
    if normalized_period == "custom" and date_from is not None:
        current_start = date_from if date_from.tzinfo else date_from.replace(tzinfo=timezone.utc)
        current_start = current_start.replace(microsecond=0)
    else:
        days = 30
        if normalized_period == "7":
            days = 7
        elif normalized_period == "90":
            days = 90
        current_start = date_to - timedelta(days=days)

    current_span = max(timedelta(days=1), date_to - current_start)
    previous_end = current_start
    previous_start = previous_end - current_span
    return current_start, date_to, previous_start, previous_end


def _category_score_value(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("score")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


def _ensure_actor_matches_manager(actor: Actor, manager_id: str) -> None:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own AI insights")


def _ensure_actor_matches_manager_scope(actor: Actor, manager_id: str, detail: str) -> None:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail=detail)


def _normalize_category_scores(category_scores: dict | None) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_key, category_key in RUBRIC_CATEGORY_KEYS.items():
        value = _category_score_value((category_scores or {}).get(raw_key))
        if value is not None and category_key not in normalized:
            normalized[category_key] = value
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


def _clamp_score(value: float) -> float:
    return max(0.0, min(10.0, value))


def _volatility_label_score(value: float) -> float:
    return round(value, 2) if value > 0 else 0.0


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_transcript_turns(turns: list[SessionTurn]) -> list[dict[str, Any]]:
    return [
        {
            "turn_id": turn.id,
            "turn_index": turn.turn_index,
            "speaker": turn.speaker.value,
            "stage": turn.stage,
            "text": turn.text,
            "started_at": turn.started_at.isoformat(),
            "ended_at": turn.ended_at.isoformat(),
        }
        for turn in turns
    ]


def _build_stage_timeline(turns: list[SessionTurn]) -> list[dict[str, Any]]:
    stage_timeline: list[dict[str, Any]] = []
    last_stage = None
    for turn in turns:
        if turn.stage == last_stage:
            continue
        stage_timeline.append(
            {
                "stage": turn.stage,
                "entered_at": turn.started_at.isoformat(),
                "turn_index": turn.turn_index,
                "speaker": turn.speaker.value,
            }
        )
        last_stage = turn.stage
    return stage_timeline


def _get_authorized_manager(db: Session, actor: Actor, manager_id: str, detail: str) -> User:
    _ensure_actor_matches_manager_scope(actor, manager_id, detail)
    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    return manager


def _serialize_chat_payload(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _list_manager_team_reps(db: Session, manager: User) -> list[User]:
    if not manager.team_id:
        return []
    return db.scalars(
        select(User).where(User.team_id == manager.team_id, User.role == UserRole.REP).order_by(User.name.asc())
    ).all()


def _resolve_rep_for_chat(db: Session, manager: User, requested_name: str | None) -> User | None:
    normalized_query = " ".join((requested_name or "").lower().split())
    if not normalized_query:
        return None

    reps = _list_manager_team_reps(db, manager)
    if not reps:
        return None

    query_tokens = set(normalized_query.split())
    best_match: tuple[float, User | None] = (0.0, None)
    for rep in reps:
        normalized_name = " ".join(rep.name.lower().split())
        name_tokens = set(normalized_name.split())
        score = SequenceMatcher(None, normalized_query, normalized_name).ratio()
        if normalized_query in normalized_name:
            score += 0.35
        overlap = len(query_tokens & name_tokens)
        if overlap:
            score += overlap / max(len(query_tokens), len(name_tokens))
        if score > best_match[0]:
            best_match = (score, rep)

    return best_match[1] if best_match[0] >= 0.45 else None


def _build_rep_risk_detail_response(
    db: Session,
    *,
    manager_id: str,
    manager: User,
    period: int,
) -> RepRiskDetailResponse:
    team = db.scalar(select(Team).where(Team.id == manager.team_id)) if manager.team_id else None
    if team is None:
        return RepRiskDetailResponse(
            manager_id=manager_id,
            period=str(period),
            generated_at=datetime.now(timezone.utc).isoformat(),
            reps=[],
            team_avg_score=None,
            team_category_averages={},
        )

    reps = db.scalars(
        select(User).where(User.team_id == team.id, User.role == UserRole.REP).order_by(User.name.asc())
    ).all()
    if not reps:
        return RepRiskDetailResponse(
            manager_id=manager_id,
            period=str(period),
            generated_at=datetime.now(timezone.utc).isoformat(),
            reps=[],
            team_avg_score=None,
            team_category_averages={},
        )

    rep_ids = [rep.id for rep in reps]
    current_end = datetime.now(timezone.utc).replace(microsecond=0)
    current_start = current_end - timedelta(days=period)
    stall_cutoff = current_end - timedelta(days=14)

    session_rows = db.execute(
        select(
            DrillSession.id.label("session_id"),
            DrillSession.rep_id.label("rep_id"),
            DrillSession.started_at.label("started_at"),
            DrillSession.ended_at.label("ended_at"),
            DrillSession.status.label("status"),
            Scorecard.overall_score.label("overall_score"),
            Scorecard.category_scores.label("category_scores"),
        )
        .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
        .where(
            DrillSession.rep_id.in_(rep_ids),
            DrillSession.started_at <= current_end,
        )
        .order_by(DrillSession.rep_id.asc(), DrillSession.started_at.asc(), DrillSession.id.asc())
    ).mappings().all()

    sessions_by_rep: dict[str, list[dict]] = defaultdict(list)
    team_period_scores: list[float] = []
    team_category_samples: dict[str, list[float]] = defaultdict(list)

    for row in session_rows:
        started_at = row["started_at"]
        normalized_started_at = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
        record = {
            "session_id": row["session_id"],
            "rep_id": row["rep_id"],
            "started_at": normalized_started_at,
            "ended_at": row["ended_at"],
            "status": row["status"],
            "overall_score": float(row["overall_score"]) if row["overall_score"] is not None else None,
            "category_scores": row["category_scores"] or {},
        }
        sessions_by_rep[row["rep_id"]].append(record)

        if normalized_started_at < current_start or record["overall_score"] is None:
            continue
        team_period_scores.append(record["overall_score"])
        for category_key, value in _normalize_category_scores(record["category_scores"]).items():
            team_category_samples[category_key].append(value)

    team_avg_score = round(sum(team_period_scores) / len(team_period_scores), 2) if team_period_scores else None
    team_category_averages = {
        category_key: round(sum(values) / len(values), 2)
        for category_key, values in team_category_samples.items()
        if values
    }

    response_rows = []
    for rep in reps:
        rep_sessions = sessions_by_rep.get(rep.id, [])
        period_sessions = [row for row in rep_sessions if row["started_at"] >= current_start]
        scored_period_sessions = [row for row in period_sessions if row["overall_score"] is not None]
        scored_sessions = [row for row in rep_sessions if row["overall_score"] is not None]

        period_scores = [row["overall_score"] for row in scored_period_sessions]
        current_avg_score = round(sum(period_scores) / len(period_scores), 2) if period_scores else None

        recent_eight_scores = [row["overall_score"] for row in scored_sessions[-8:]]
        recent_ten_scores = [row["overall_score"] for row in scored_sessions[-10:]]

        recent_average_score = (
            round(sum(recent_ten_scores) / len(recent_ten_scores), 2) if recent_ten_scores else None
        )
        current_score_reference = current_avg_score if current_avg_score is not None else recent_average_score

        score_volatility = (
            _volatility_label_score(pstdev(recent_eight_scores))
            if len(recent_eight_scores) >= 2
            else 0.0
        )
        score_trend_slope = _linear_regression_slope(recent_ten_scores)
        rounded_slope = round(score_trend_slope, 4) if score_trend_slope is not None else None

        plateau_detected = len(recent_eight_scores) >= 8 and pstdev(recent_eight_scores) < 0.4
        decline_detected = rounded_slope is not None and rounded_slope < -0.15
        breakthrough_detected = (
            rounded_slope is not None
            and rounded_slope > 0.2
            and current_score_reference is not None
            and current_score_reference > 7.5
        )

        last_session = rep_sessions[-1] if rep_sessions else None
        days_since_last_session = (
            max(0, (current_end.date() - last_session["started_at"].date()).days)
            if last_session is not None
            else None
        )
        stall_detected = bool(rep_sessions) and not any(row["started_at"] >= stall_cutoff for row in rep_sessions)

        projected_score_10_sessions = (
            round(_clamp_score(current_score_reference + (rounded_slope * 10)), 2)
            if current_score_reference is not None and rounded_slope is not None
            else None
        )

        category_source_sessions = scored_period_sessions if scored_period_sessions else scored_sessions[-10:]
        rep_category_samples: dict[str, list[float]] = defaultdict(list)
        for row in category_source_sessions:
            for category_key, value in _normalize_category_scores(row["category_scores"]).items():
                rep_category_samples[category_key].append(value)

        most_vulnerable_category: str | None = None
        category_gap_vs_team: float | None = None
        for category_key in TEAM_RISK_CATEGORY_KEYS:
            rep_values = rep_category_samples.get(category_key)
            team_average = team_category_averages.get(category_key)
            if not rep_values or team_average is None:
                continue
            rep_average = sum(rep_values) / len(rep_values)
            gap = round(team_average - rep_average, 2)
            if gap <= 0:
                continue
            if category_gap_vs_team is None or gap > category_gap_vs_team:
                category_gap_vs_team = gap
                most_vulnerable_category = category_key

        risk_score = 0.0
        if current_score_reference is not None:
            if current_score_reference < 6.0:
                risk_score += 20
            elif current_score_reference < 7.0:
                risk_score += 12
        if decline_detected:
            risk_score += 22
        if plateau_detected:
            risk_score += 10
        if stall_detected:
            risk_score += 35 + min(15, max(0, (days_since_last_session or 14) - 14) * 2)
        if projected_score_10_sessions is not None:
            if projected_score_10_sessions < 6.0:
                risk_score += 15
            elif projected_score_10_sessions < 7.0:
                risk_score += 8
        if score_volatility >= 1.2:
            risk_score += 8
        if category_gap_vs_team is not None:
            if category_gap_vs_team >= 1.5:
                risk_score += 10
            elif category_gap_vs_team >= 0.75:
                risk_score += 5
        if breakthrough_detected:
            risk_score -= 18
        elif rounded_slope is not None and rounded_slope > 0.1:
            risk_score -= 5

        risk_score = round(max(0.0, min(100.0, risk_score)), 2)

        red_flag_count = sum(
            1
            for condition in (
                plateau_detected,
                decline_detected,
                stall_detected,
                current_score_reference is not None and current_score_reference < 6.0,
                projected_score_10_sessions is not None and projected_score_10_sessions < 6.0,
                category_gap_vs_team is not None and category_gap_vs_team >= 1.5,
            )
            if condition
        )

        if risk_score >= 45:
            risk_level = "high"
        elif risk_score >= 22:
            risk_level = "medium"
        else:
            risk_level = "low"

        response_rows.append(
            {
                "rep_id": rep.id,
                "rep_name": rep.name,
                "current_avg_score": current_avg_score,
                "score_trend_slope": round(rounded_slope, 4) if rounded_slope is not None else None,
                "score_volatility": score_volatility,
                "projected_score_10_sessions": projected_score_10_sessions,
                "plateau_detected": plateau_detected,
                "decline_detected": decline_detected,
                "breakthrough_detected": breakthrough_detected,
                "stall_detected": stall_detected,
                "days_since_last_session": days_since_last_session,
                "most_vulnerable_category": most_vulnerable_category,
                "category_gap_vs_team": category_gap_vs_team,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "session_count": len(period_sessions),
                "red_flag_count": red_flag_count,
            }
        )

    response_rows.sort(key=lambda item: (item["risk_score"], item["red_flag_count"], item["session_count"]), reverse=True)

    return RepRiskDetailResponse(
        manager_id=manager_id,
        period=str(period),
        generated_at=current_end.isoformat(),
        reps=response_rows,
        team_avg_score=team_avg_score,
        team_category_averages=team_category_averages,
    )


def _get_live_sessions_payload(db: Session, manager_id: str, actor: Actor) -> LiveSessionsResponse:
    manager = _get_authorized_manager(db, actor, manager_id, "manager can only access their own live sessions")
    checked_at = datetime.now(timezone.utc)
    if not manager.team_id:
        return LiveSessionsResponse(manager_id=manager_id, live_sessions=[], checked_at=checked_at.isoformat())

    turn_stats_subquery = (
        select(
            SessionTurn.session_id.label("session_id"),
            func.count(SessionTurn.id).label("turn_count"),
            func.max(SessionTurn.turn_index).label("max_turn_index"),
        )
        .group_by(SessionTurn.session_id)
        .subquery()
    )
    latest_stage_subquery = (
        select(
            SessionTurn.session_id.label("session_id"),
            SessionTurn.stage.label("stage"),
        )
        .join(
            turn_stats_subquery,
            and_(
                turn_stats_subquery.c.session_id == SessionTurn.session_id,
                turn_stats_subquery.c.max_turn_index == SessionTurn.turn_index,
            ),
        )
        .subquery()
    )

    rows = db.execute(
        select(
            DrillSession,
            User.name.label("rep_name"),
            Scenario.name.label("scenario_name"),
            Scenario.difficulty.label("scenario_difficulty"),
            turn_stats_subquery.c.turn_count,
            latest_stage_subquery.c.stage,
        )
        .join(User, User.id == DrillSession.rep_id)
        .join(Scenario, Scenario.id == DrillSession.scenario_id)
        .outerjoin(turn_stats_subquery, turn_stats_subquery.c.session_id == DrillSession.id)
        .outerjoin(latest_stage_subquery, latest_stage_subquery.c.session_id == DrillSession.id)
        .where(
            DrillSession.status == SessionStatus.ACTIVE,
            User.role == UserRole.REP,
            User.team_id == manager.team_id,
        )
        .order_by(DrillSession.started_at.desc())
    ).all()

    live_sessions = [
        LiveSessionCard(
            session_id=session.id,
            rep_id=session.rep_id,
            rep_name=rep_name,
            scenario_id=session.scenario_id,
            scenario_name=scenario_name,
            scenario_difficulty=scenario_difficulty,
            started_at=(_as_utc(session.started_at) or checked_at).isoformat(),
            elapsed_seconds=max(0, int((checked_at - (_as_utc(session.started_at) or checked_at)).total_seconds())),
            stage=stage,
            turn_count=int(turn_count or 0),
        )
        for session, rep_name, scenario_name, scenario_difficulty, turn_count, stage in rows
    ]
    return LiveSessionsResponse(
        manager_id=manager_id,
        live_sessions=live_sessions,
        checked_at=checked_at.isoformat(),
    )


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

    analytics_refresh_service.refresh_manager(db, manager_id=manager.id)
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

    analytics_refresh_service.refresh_manager(db, manager_id=manager.id)
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
    rep_id: str | None = Query(default=None),
    scenario_id: str | None = Query(default=None),
    reviewed: bool | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> ManagerFeedResponse:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own feed")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    items = feed_service.get_feed(
        db,
        manager_id=manager_id,
        rep_id=rep_id,
        scenario_id=scenario_id,
        reviewed=reviewed,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return ManagerFeedResponse(items=items)


@router.get("/reps/{rep_id}/progress")
def get_rep_progress(
    rep_id: str,
    manager_id: str = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=30, ge=1, le=100),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
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

    current_end = date_to or datetime.now(timezone.utc)
    if current_end.tzinfo is None:
        current_end = current_end.replace(tzinfo=timezone.utc)

    if date_from is not None:
        current_start = date_from if date_from.tzinfo else date_from.replace(tzinfo=timezone.utc)
    else:
        current_start = current_end - timedelta(days=days)

    # Strip timezone for comparison — SQLite stores datetimes as naive UTC strings,
    # and passing tz-aware datetimes as bind parameters can produce incorrect string
    # comparisons.  Always normalise to UTC-naive before building the WHERE clause.
    current_start_naive = current_start.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
    current_end_naive = current_end.astimezone(timezone.utc).replace(tzinfo=None)

    stmt = (
        select(
            DrillSession.id.label("session_id"),
            DrillSession.started_at.label("started_at"),
            DrillSession.status.label("status"),
            Scorecard.overall_score.label("overall_score"),
            Scorecard.category_scores.label("category_scores"),
            DrillSession.scenario_id.label("scenario_id"),
            Scenario.name.label("scenario_name"),
        )
        .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
        .join(Scenario, Scenario.id == DrillSession.scenario_id)
        .where(DrillSession.started_at >= current_start_naive)
        .where(DrillSession.started_at <= current_end_naive)
        .where(DrillSession.rep_id == rep_id)
        .order_by(DrillSession.started_at.desc())
    )
    rows = db.execute(stmt).mappings().all()
    scores = [float(row["overall_score"]) for row in rows if row["overall_score"] is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None
    trend_rows = [row for row in rows if row["overall_score"] is not None][:limit]

    category_samples: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        category_scores = row["category_scores"] or {}
        for raw_key, normalized in RUBRIC_CATEGORY_KEYS.items():
            if raw_key not in category_scores:
                continue
            value = _category_score_value(category_scores.get(raw_key))
            if value is not None:
                category_samples[normalized].append(value)

    category_averages = {
        key: round(sum(values) / len(values), 2)
        for key, values in category_samples.items()
        if values
    }
    weak_area_tags = [key for key, value in category_averages.items() if value < 6.0]

    return {
        "rep_id": rep_id,
        "rep_name": rep.name,
        "days": days,
        "date_from": current_start.isoformat(),
        "date_to": current_end.isoformat(),
        "session_count": len(rows),
        "scored_session_count": len(scores),
        "average_score": avg_score,
        "current_period_category_averages": category_averages,
        "weak_area_tags": weak_area_tags,
        "latest_sessions": [
            {
                "session_id": row["session_id"],
                "scenario_id": row["scenario_id"],
                "scenario_name": row["scenario_name"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "status": row["status"].value if row["status"] else None,
                "overall_score": row["overall_score"],
            }
            for row in rows[:limit]
        ],
        "trend": [
            {
                "session_id": row["session_id"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "overall_score": row["overall_score"],
            }
            for row in reversed(trend_rows)
        ],
    }


@router.get("/analytics")
def get_manager_analytics(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    current_start, current_end, previous_start, previous_end = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )

    return management_analytics_service.get_team_analytics(
        db,
        manager_id=manager_id,
        period=period,
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
    )


@router.get("/analytics/team")
def get_manager_team_analytics(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    return get_manager_analytics(
        manager_id=manager_id,
        period=period,
        date_from=date_from,
        date_to=date_to,
        actor=actor,
        db=db,
    )


@router.get("/command-center")
def get_command_center(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    current_start, current_end, previous_start, previous_end = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    return management_analytics_service.get_command_center(
        db,
        manager_id=manager_id,
        date_from=current_start,
        date_to=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
        period=period,
    )


@router.get("/analytics/scenarios")
def get_scenario_intelligence(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    current_start, current_end, _, _ = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    return management_analytics_service.get_scenario_intelligence(
        db,
        manager_id=manager_id,
        date_from=current_start,
        date_to=current_end,
        period=period,
    )


@router.get("/analytics/coaching")
def get_coaching_analytics(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    current_start, current_end, _, _ = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    return management_analytics_service.get_coaching_analytics(
        db,
        manager_id=manager_id,
        date_from=current_start,
        date_to=current_end,
        period=period,
    )


@router.get("/analytics/calibration", response_model=CalibrationAnalyticsResponse)
def get_calibration_analytics(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> CalibrationAnalyticsResponse:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    current_start, current_end, _, _ = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    rows = db.scalars(
        select(AnalyticsFactManagerCalibration)
        .where(AnalyticsFactManagerCalibration.manager_id == manager_id)
        .order_by(AnalyticsFactManagerCalibration.reviewed_at.desc())
    ).all()
    items = []
    for row in rows:
        reviewed_at = row.reviewed_at
        if reviewed_at is None:
            continue
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
        if row.override_score is None or row.ai_score is None or abs(float(row.delta_score or 0.0)) < DISAGREEMENT_THRESHOLD:
            continue
        source_session = db.scalar(select(DrillSession).where(DrillSession.id == row.session_id))
        rep = _get_user_or_404(db, source_session.rep_id, "rep") if source_session is not None else None
        grading_run = db.scalar(
            select(GradingRun)
            .where(GradingRun.session_id == row.session_id)
            .order_by(GradingRun.completed_at.desc(), GradingRun.created_at.desc())
        )
        items.append(
            {
                "id": f"grading-disagreement-{row.review_id}",
                "review_id": row.review_id,
                "scorecard_id": row.scorecard_id,
                "session_id": row.session_id,
                "rep_id": source_session.rep_id if source_session else None,
                "rep_name": rep.name if rep else None,
                "prompt_version_id": grading_run.prompt_version_id if grading_run else None,
                "ai_score": row.ai_score,
                "override_score": row.override_score,
                "delta": row.delta_score,
                "severity": "high" if abs(float(row.delta_score or 0.0)) >= 3.5 else "medium",
                "occurred_at": reviewed_at.isoformat(),
            }
        )

    return CalibrationAnalyticsResponse(
        manager_id=manager_id,
        period=period,
        date_from=current_start.isoformat(),
        date_to=current_end.isoformat(),
        disagreement_threshold=DISAGREEMENT_THRESHOLD,
        items=items,
    )


@router.get("/analytics/rep-risk-detail", response_model=RepRiskDetailResponse)
def get_rep_risk_detail(
    manager_id: str = Query(...),
    period: int = Query(default=30, ge=1, le=365),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> RepRiskDetailResponse:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    return _build_rep_risk_detail_response(db, manager_id=manager_id, manager=manager, period=period)


@router.post("/ai/rep-insight", response_model=RepInsightResponse)
def get_ai_rep_insight(
    payload: RepInsightRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> RepInsightResponse:
    _ensure_actor_matches_manager(actor, payload.manager_id)

    manager = _get_user_or_404(db, payload.manager_id, "manager")
    rep = _get_user_or_404(db, payload.rep_id, "rep")
    _ensure_same_org(actor, manager.org_id)
    if manager.org_id != rep.org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")

    try:
        return manager_ai_service.generate_rep_insight(
            db,
            rep=rep,
            period_days=payload.period_days,
        )
    except AiCoachingDataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AiCoachingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ai/session-annotations", response_model=SessionAnnotationsResponse)
def get_ai_session_annotations(
    payload: SessionAnnotationRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> SessionAnnotationsResponse:
    _ensure_actor_matches_manager(actor, payload.manager_id)

    manager = _get_user_or_404(db, payload.manager_id, "manager")
    session = db.scalar(select(DrillSession).where(DrillSession.id == payload.session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    rep = _get_user_or_404(db, session.rep_id, "rep")
    _ensure_same_org(actor, manager.org_id)
    if manager.org_id != rep.org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")

    try:
        return manager_ai_service.generate_session_annotations(db, session_id=payload.session_id)
    except AiCoachingDataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AiCoachingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ai/team-coaching-summary", response_model=TeamCoachingSummaryResponse)
def get_ai_team_coaching_summary(
    payload: TeamCoachingSummaryRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> TeamCoachingSummaryResponse:
    _ensure_actor_matches_manager(actor, payload.manager_id)

    manager = _get_user_or_404(db, payload.manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    current_end = datetime.now(timezone.utc).replace(microsecond=0)
    current_start = (current_end - timedelta(days=payload.period_days)).replace(microsecond=0)
    coaching_analytics = management_analytics_service.get_coaching_analytics(
        db,
        manager_id=payload.manager_id,
        date_from=current_start,
        date_to=current_end,
        period="custom",
    )

    try:
        return manager_ai_service.generate_team_coaching_summary(
            manager=manager,
            period_days=payload.period_days,
            coaching_analytics=coaching_analytics,
        )
    except AiCoachingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ai/chat", response_model=ManagerChatResponse)
def chat_with_manager_ai(
    payload: ManagerChatRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> ManagerChatResponse:
    _ensure_actor_matches_manager(actor, payload.manager_id)

    manager = _get_user_or_404(db, payload.manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    try:
        classification = manager_ai_service.classify_manager_chat_intent(message=payload.message)
    except AiCoachingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    current_end = datetime.now(timezone.utc).replace(microsecond=0)
    current_start = (current_end - timedelta(days=payload.period_days)).replace(microsecond=0)
    previous_start = current_start - (current_end - current_start)
    previous_end = current_start

    relevant_data: dict[str, Any] = {
        "classification": classification.model_dump(mode="json"),
        "period_days": payload.period_days,
        "date_from": current_start.isoformat(),
        "date_to": current_end.isoformat(),
    }
    sources_used: list[str] = []

    def attach_source(source_name: str, data: Any) -> None:
        sources_used.append(source_name)
        relevant_data[source_name] = _serialize_chat_payload(data)

    if classification.intent in {"team_performance", "general"}:
        attach_source(
            "command_center",
            management_analytics_service.get_command_center(
                db,
                manager_id=payload.manager_id,
                date_from=current_start,
                date_to=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                period="custom",
            ),
        )
    elif classification.intent == "rep_specific":
        resolved_rep = _resolve_rep_for_chat(db, manager, classification.rep_name_mentioned or payload.message)
        if resolved_rep is not None:
            relevant_data["resolved_rep"] = {"rep_id": resolved_rep.id, "rep_name": resolved_rep.name}
            attach_source(
                f"rep_progress:{resolved_rep.id}",
                get_rep_progress(
                    rep_id=resolved_rep.id,
                    manager_id=payload.manager_id,
                    days=payload.period_days,
                    limit=30,
                    date_from=current_start,
                    date_to=current_end,
                    actor=actor,
                    db=db,
                ),
            )
        else:
            relevant_data["rep_lookup"] = {
                "requested_name": classification.rep_name_mentioned or payload.message,
                "matched": False,
                "available_reps": [rep.name for rep in _list_manager_team_reps(db, manager)],
            }
            attach_source(
                "command_center",
                management_analytics_service.get_command_center(
                    db,
                    manager_id=payload.manager_id,
                    date_from=current_start,
                    date_to=current_end,
                    previous_start=previous_start,
                    previous_end=previous_end,
                    period="custom",
                ),
            )
    elif classification.intent == "scenario_analysis":
        attach_source(
            "scenario_intelligence",
            management_analytics_service.get_scenario_intelligence(
                db,
                manager_id=payload.manager_id,
                date_from=current_start,
                date_to=current_end,
                period="custom",
            ),
        )
    elif classification.intent == "coaching_effectiveness":
        attach_source(
            "coaching_analytics",
            management_analytics_service.get_coaching_analytics(
                db,
                manager_id=payload.manager_id,
                date_from=current_start,
                date_to=current_end,
                period="custom",
            ),
        )
    elif classification.intent == "risk_alerts":
        attach_source(
            "rep_risk_detail",
            _build_rep_risk_detail_response(
                db,
                manager_id=payload.manager_id,
                manager=manager,
                period=payload.period_days,
            ).model_dump(mode="json"),
        )
    elif classification.intent == "comparison":
        team_reps = _list_manager_team_reps(db, manager)
        attach_source(
            "command_center",
            management_analytics_service.get_command_center(
                db,
                manager_id=payload.manager_id,
                date_from=current_start,
                date_to=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                period="custom",
            ),
        )
        attach_source(
            "rep_progress_collection",
            {
                "items": [
                    {
                        "rep_id": rep.id,
                        "rep_name": rep.name,
                        "progress": get_rep_progress(
                            rep_id=rep.id,
                            manager_id=payload.manager_id,
                            days=payload.period_days,
                            limit=30,
                            date_from=current_start,
                            date_to=current_end,
                            actor=actor,
                            db=db,
                        ),
                    }
                    for rep in team_reps
                ]
            },
        )

    try:
        answer = manager_ai_service.answer_manager_chat(
            period_days=payload.period_days,
            message=payload.message,
            conversation_history=[item.model_dump(mode="json") for item in payload.conversation_history],
            relevant_data=relevant_data,
        )
    except AiCoachingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ManagerChatResponse(
        **answer.model_dump(),
        intent_detected=classification.intent,
        sources_used=sources_used,
    )


@router.get("/analytics/reps/{rep_id}")
def get_rep_analytics(
    rep_id: str,
    manager_id: str = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=30, ge=1, le=100),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    return get_rep_progress(
        rep_id=rep_id,
        manager_id=manager_id,
        days=days,
        limit=limit,
        date_from=None,
        date_to=None,
        actor=actor,
        db=db,
    )


@router.get("/analytics/explorer")
def get_session_explorer(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    rep_id: str | None = Query(default=None),
    scenario_id: str | None = Query(default=None),
    reviewed: bool | None = Query(default=None),
    weakness_tag: str | None = Query(default=None),
    score_min: float | None = Query(default=None),
    score_max: float | None = Query(default=None),
    barge_in_only: bool = Query(default=False),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    current_start, current_end, _, _ = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    return management_analytics_service.get_session_explorer(
        db,
        manager_id=manager_id,
        date_from=current_start,
        date_to=current_end,
        rep_id=rep_id,
        scenario_id=scenario_id,
        reviewed=reviewed,
        weakness_tag=weakness_tag,
        score_min=score_min,
        score_max=score_max,
        barge_in_only=barge_in_only,
        search=search,
        limit=limit,
    )


@router.get("/alerts")
def get_manager_alerts(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    current_start, current_end, _, _ = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    return management_analytics_service.get_alerts(
        db,
        manager_id=manager_id,
        date_from=current_start,
        date_to=current_end,
        period=period,
    )


@router.post("/alerts/{alert_id}/ack")
def acknowledge_manager_alert(
    alert_id: str,
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only acknowledge their own alerts")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)

    alert_row = db.scalar(
        select(AnalyticsFactAlert)
        .where(
            AnalyticsFactAlert.manager_id == manager_id,
            AnalyticsFactAlert.alert_key == alert_id,
            AnalyticsFactAlert.is_active.is_(True),
        )
        .order_by(AnalyticsFactAlert.occurred_at.desc())
        .limit(1)
    )
    if alert_row is None:
        raise HTTPException(status_code=404, detail="alert not found")

    action = action_service.log(
        db,
        manager_id=manager_id,
        action_type="alert.acknowledged",
        target_type="alert",
        target_id=alert_id,
        summary=f"Acknowledged {alert_row.kind} alert",
        payload={
            "alert_id": alert_id,
            "period_key": alert_row.period_key,
            "severity": alert_row.severity,
            "kind": alert_row.kind,
            "title": alert_row.title,
            "session_id": alert_row.session_id,
            "rep_id": alert_row.rep_id,
            "scenario_id": alert_row.scenario_id,
        },
    )
    refresh = analytics_refresh_service.refresh_manager(db, manager_id=manager_id)
    db.commit()
    db.refresh(action)
    return {
        "status": "acknowledged",
        "alert_id": alert_id,
        "manager_id": manager_id,
        "action_id": action.id,
        "refresh": refresh,
    }


@router.get("/benchmarks")
def get_manager_benchmarks(
    manager_id: str = Query(...),
    period: str = Query(default="30"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    current_start, current_end, _, _ = _resolve_period_bounds(
        period=period,
        date_from=date_from,
        date_to=date_to,
    )
    return management_analytics_service.get_benchmarks(
        db,
        manager_id=manager_id,
        date_from=current_start,
        date_to=current_end,
        period=period,
    )


@router.get("/analytics/operations")
def get_manager_analytics_operations(
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    return management_analytics_service.get_operations_status(db, manager_id=manager_id)


@router.get("/analytics/metrics/definitions")
def get_manager_metric_definitions(
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own analytics")

    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    return management_analytics_service.get_metric_definitions(db, manager_id=manager_id)


@router.get("/sessions/live", response_model=LiveSessionsResponse)
def get_live_sessions(
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> LiveSessionsResponse:
    return _get_live_sessions_payload(db, manager_id, actor)


@router.get("/sessions/live/stream")
async def stream_live_sessions(
    request: Request,
    manager_id: str = Query(...),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    actor = resolve_ws_actor_with_query(request.headers, request.query_params, db)
    if actor is None:
        raise HTTPException(status_code=401, detail="missing authentication")
    if actor.role not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail="manager role required")

    _get_authorized_manager(db, actor, manager_id, "manager can only stream their own live sessions")

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            db.rollback()
            payload = _get_live_sessions_payload(db, manager_id, actor)
            yield f"data: {json.dumps(payload.model_dump(mode='json'))}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions/{session_id}/live-transcript", response_model=LiveSessionTranscriptResponse)
def get_live_transcript(
    session_id: str,
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> LiveSessionTranscriptResponse:
    manager = _get_authorized_manager(db, actor, manager_id, "manager can only access their own live sessions")
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    rep = _get_user_or_404(db, session.rep_id, "rep")
    _ensure_same_org(actor, rep.org_id)
    if manager.team_id and actor.role == "manager" and rep.team_id != manager.team_id:
        raise HTTPException(status_code=403, detail="session does not belong to this manager's team")

    scenario = db.scalar(select(Scenario).where(Scenario.id == session.scenario_id))
    turns = db.scalars(
        select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())
    ).all()
    checked_at = datetime.now(timezone.utc)
    started_at = _as_utc(session.started_at)
    ended_at = _as_utc(session.ended_at) or checked_at

    return LiveSessionTranscriptResponse(
        session_id=session.id,
        status=session.status.value,
        started_at=started_at.isoformat() if started_at else None,
        ended_at=ended_at.isoformat() if session.ended_at else None,
        elapsed_seconds=max(0, int((ended_at - started_at).total_seconds())) if started_at else 0,
        stage=turns[-1].stage if turns else None,
        turn_count=len(turns),
        rep={"id": rep.id, "name": rep.name},
        scenario=(
            {
                "id": scenario.id,
                "name": scenario.name,
                "difficulty": scenario.difficulty,
            }
            if scenario
            else None
        ),
        turns=_serialize_transcript_turns(turns),
        stage_timeline=_build_stage_timeline(turns),
    )


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
                "scorecard_schema_version": scorecard.scorecard_schema_version,
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
    scenario = db.scalar(select(Scenario).where(Scenario.id == session.scenario_id))

    turns = db.scalars(select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())).all()
    scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
    reviews: list[ManagerReview] = []
    coaching_notes: list[ManagerCoachingNote] = []
    if scorecard is not None:
        reviews = db.scalars(
            select(ManagerReview)
            .where(ManagerReview.scorecard_id == scorecard.id)
            .order_by(ManagerReview.reviewed_at.desc())
        ).all()
        coaching_notes = review_service.list_coaching_notes(db, scorecard_id=scorecard.id)
    artifacts = db.scalars(
        select(SessionArtifact).where(SessionArtifact.session_id == session_id, SessionArtifact.artifact_type == "audio")
    ).all()
    state_events = db.scalars(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id, SessionEvent.event_type == "server.session.state")
        .order_by(SessionEvent.event_ts.asc())
    ).all()
    committed_events = db.scalars(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id, SessionEvent.event_type == "server.turn.committed")
        .order_by(SessionEvent.event_ts.asc())
    ).all()

    transcript_turns = _serialize_transcript_turns(turns)
    objection_timeline = [
        {"turn_id": t.id, "turn_index": t.turn_index, "objection_tags": t.objection_tags}
        for t in turns
        if t.objection_tags
    ]
    stage_timeline = _build_stage_timeline(turns)

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

    micro_behavior_timeline = []
    realism_scores: list[float] = []
    for event in committed_events:
        micro_behavior = event.payload.get("micro_behavior")
        if not isinstance(micro_behavior, dict):
            continue
        realism_score = micro_behavior.get("realism_score")
        if isinstance(realism_score, (int, float)):
            realism_scores.append(float(realism_score))
        micro_behavior_timeline.append(
            {
                "event_id": event.event_id,
                "recorded_at": event.event_ts.isoformat(),
                "rep_turn_id": event.payload.get("rep_turn_id"),
                "ai_turn_id": event.payload.get("ai_turn_id"),
                "stage": event.payload.get("stage"),
                "emotion": event.payload.get("emotion_after") or event.payload.get("emotion"),
                "tone": micro_behavior.get("tone"),
                "sentence_length": micro_behavior.get("sentence_length"),
                "behaviors": micro_behavior.get("behaviors", []),
                "interruption_type": micro_behavior.get("interruption_type"),
                "pause_profile": micro_behavior.get("pause_profile", {}),
                "realism_score": realism_score,
                "filler": bool(event.payload.get("filler", False)),
            }
        )

    conversational_realism = {
        "turn_count": len(realism_scores),
        "average_score": round(sum(realism_scores) / len(realism_scores), 1) if realism_scores else None,
        "latest_score": realism_scores[-1] if realism_scores else None,
        "min_score": min(realism_scores) if realism_scores else None,
        "max_score": max(realism_scores) if realism_scores else None,
    }

    return SessionReplayResponse(
        session_id=session.id,
        status=session.status.value,
        rep={
            "id": rep.id,
            "name": rep.name,
            "email": rep.email,
            "team_id": rep.team_id,
        },
        scenario=(
            {
                "id": scenario.id,
                "name": scenario.name,
                "industry": scenario.industry,
                "difficulty": scenario.difficulty,
            }
            if scenario
            else None
        ),
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
        micro_behavior_timeline=micro_behavior_timeline,
        interruption_timeline=interruption_timeline,
        stage_timeline=stage_timeline,
        conversational_realism=conversational_realism,
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
                "scorecard_schema_version": scorecard.scorecard_schema_version,
                "category_scores": scorecard.category_scores,
                "highlights": scorecard.highlights,
                "ai_summary": scorecard.ai_summary,
                "evidence_turn_ids": scorecard.evidence_turn_ids,
                "weakness_tags": scorecard.weakness_tags,
            }
            if scorecard
            else None
        ),
        manager_reviews=[_serialize_review(review) for review in reviews],
        coaching_notes=[_serialize_coaching_note(note) for note in coaching_notes],
        latest_coaching_note=_serialize_coaching_note(coaching_notes[0]) if coaching_notes else None,
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

    review = action_service.submit_review(
        db,
        reviewer=reviewer,
        scorecard=scorecard,
        source_session=source_session,
        reason_code=ReviewReason(payload.reason_code),
        override_score=payload.override_score,
        notes=payload.notes,
    )

    analytics_refresh_service.refresh_session(db, session_id=source_session.id)

    db.commit()
    db.refresh(review)
    return review


@router.post("/sessions/bulk-review", response_model=BulkReviewResponse)
def bulk_review_sessions(
    payload: BulkReviewRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> BulkReviewResponse:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated reviewer required")

    reviewer = _get_user_or_404(db, actor.user_id, "reviewer")
    _ensure_same_org(actor, reviewer.org_id)

    result = review_service.bulk_mark_reviewed(
        db,
        reviewer=reviewer,
        session_ids=payload.session_ids,
        idempotency_key=payload.idempotency_key,
        notes=payload.notes,
    )

    if result["created_count"]:
        action_service.log(
            db,
            manager_id=reviewer.id,
            action_type="scorecard.bulk_reviewed",
            target_type="session_batch",
            target_id=payload.idempotency_key,
            summary="Manager marked multiple scored sessions reviewed",
            payload={
                "created_count": result["created_count"],
                "requested_count": result["requested_count"],
                "session_ids": payload.session_ids,
            },
        )
        for item in result["items"]:
            if item.get("status") == "created":
                analytics_refresh_service.refresh_session(db, session_id=item["session_id"])
    db.commit()
    return BulkReviewResponse.model_validate(result)


@router.post("/scorecards/{scorecard_id}/coaching-notes", response_model=ManagerCoachingNoteResponse)
def create_coaching_note(
    scorecard_id: str,
    payload: CoachingNoteCreateRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> ManagerCoachingNoteResponse:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated reviewer required")

    reviewer = _get_user_or_404(db, actor.user_id, "reviewer")
    _ensure_same_org(actor, reviewer.org_id)

    coaching_note = review_service.create_coaching_note(
        db,
        scorecard_id=scorecard_id,
        reviewer=reviewer,
        note=payload.note,
        visible_to_rep=payload.visible_to_rep,
        weakness_tags=payload.weakness_tags,
    )
    if coaching_note is None:
        raise HTTPException(status_code=404, detail="scorecard not found or not owned by reviewer")

    action_service.log(
        db,
        manager_id=reviewer.id,
        action_type="scorecard.coaching_note_added",
        target_type="scorecard",
        target_id=scorecard_id,
        summary="Manager added coaching note to scorecard",
        payload={
            "visible_to_rep": payload.visible_to_rep,
            "weakness_tags": payload.weakness_tags,
        },
    )
    analytics_refresh_service.refresh_session(db, session_id=coaching_note.scorecard.session_id)
    db.commit()
    db.refresh(coaching_note)
    return _serialize_coaching_note(coaching_note)


@router.get("/scorecards/{scorecard_id}/coaching-notes", response_model=list[ManagerCoachingNoteResponse])
def get_coaching_notes(
    scorecard_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> list[ManagerCoachingNoteResponse]:
    if not actor.user_id:
        raise HTTPException(status_code=401, detail="authenticated reviewer required")

    reviewer = _get_user_or_404(db, actor.user_id, "reviewer")
    _ensure_same_org(actor, reviewer.org_id)

    scorecard = db.scalar(select(Scorecard).where(Scorecard.id == scorecard_id))
    if scorecard is None:
        raise HTTPException(status_code=404, detail="scorecard not found")

    session = db.scalar(select(DrillSession).where(DrillSession.id == scorecard.session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="source session not found")

    assignment = db.scalar(select(Assignment).where(Assignment.id == session.assignment_id))
    if assignment is None or (reviewer.role != UserRole.ADMIN and assignment.assigned_by != reviewer.id):
        raise HTTPException(status_code=403, detail="cannot access coaching notes for another manager's session")

    notes = review_service.list_coaching_notes(db, scorecard_id=scorecard_id)
    return [_serialize_coaching_note(note) for note in notes]


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
    status: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own notifications")
    manager = _get_user_or_404(db, manager_id, "manager")
    _ensure_same_org(actor, manager.org_id)
    rows = notification_service.list_manager_notifications(
        db,
        manager_id=manager_id,
        status=status,
        channel=channel,
        session_id=session_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
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


@router.get("/reps/{rep_id}/adaptive-plan", response_model=AdaptiveTrainingPlanResponse)
def get_adaptive_training_plan(
    rep_id: str,
    manager_id: str = Query(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> AdaptiveTrainingPlanResponse:
    if actor.user_id and actor.role == "manager" and actor.user_id != manager_id:
        raise HTTPException(status_code=403, detail="manager can only access their own adaptive plans")
    return adaptive_training_service.build_plan(db, rep_id=rep_id)


@router.post("/reps/{rep_id}/adaptive-assignment", response_model=AdaptiveAssignmentResponse)
def create_adaptive_assignment(
    rep_id: str,
    payload: AdaptiveAssignmentRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> AdaptiveAssignmentResponse:
    if actor.user_id and actor.role == "manager" and actor.user_id != payload.assigned_by:
        raise HTTPException(status_code=403, detail="manager can only assign as themselves")

    if payload.scenario_id is not None:
        scenario = db.scalar(select(Scenario).where(Scenario.id == payload.scenario_id))
        if scenario is None:
            raise HTTPException(status_code=404, detail="scenario not found")

    try:
        result = adaptive_training_service.create_adaptive_assignment(
            db,
            rep_id=rep_id,
            assigned_by=payload.assigned_by,
            due_at=payload.due_at,
            min_score_target=payload.min_score_target,
            retry_policy=payload.retry_policy,
            scenario_id=payload.scenario_id,
        )
    except ValueError as exc:
        message = str(exc)
        if "scenario not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    return {
        "assignment": AssignmentResponse.model_validate(result["assignment"]).model_dump(),
        "adaptive_plan": result["adaptive_plan"],
        "selected_scenario": result["selected_scenario"],
    }
