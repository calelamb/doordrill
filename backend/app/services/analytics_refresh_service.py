from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import pstdev
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.analytics import (
    AnalyticsDimManager,
    AnalyticsDimRep,
    AnalyticsDimScenario,
    AnalyticsDimTeam,
    AnalyticsDimTime,
    AnalyticsFactAlert,
    AnalyticsFactCoachingIntervention,
    AnalyticsFactManagerCalibration,
    AnalyticsFactRepDay,
    AnalyticsFactRepWeek,
    AnalyticsFactScenarioDay,
    AnalyticsFactSession,
    AnalyticsFactSessionTurnMetrics,
    AnalyticsFactTeamDay,
    AnalyticsMaterializedView,
    AnalyticsMetricDefinition,
    AnalyticsMetricSnapshot,
    AnalyticsPartitionWindow,
    AnalyticsRefreshRun,
)
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.scenario import Scenario
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.types import AssignmentStatus, TurnSpeaker, UserRole
from app.models.user import Team, User
from app.services.management_analytics_service import ManagementAnalyticsService

METRIC_DEFINITIONS = [
    {
        "metric_key": "team_average_score",
        "display_name": "Team Average Score",
        "description": "Average overall score across scored sessions.",
        "entity_type": "team",
        "aggregation_method": "avg",
    },
    {
        "metric_key": "completion_rate",
        "display_name": "Completion Rate",
        "description": "Completed assignments divided by assignments created.",
        "entity_type": "team",
        "aggregation_method": "ratio",
    },
    {
        "metric_key": "review_coverage_rate",
        "display_name": "Review Coverage Rate",
        "description": "Reviewed scored sessions divided by scored sessions.",
        "entity_type": "team",
        "aggregation_method": "ratio",
    },
    {
        "metric_key": "reps_at_risk",
        "display_name": "Reps At Risk",
        "description": "Count of reps with weak recent average score or negative delta.",
        "entity_type": "team",
        "aggregation_method": "count",
    },
    {
        "metric_key": "scenario_pass_rate",
        "display_name": "Scenario Pass Rate",
        "description": "Pass rate per scenario based on the 7.0 score threshold.",
        "entity_type": "scenario",
        "aggregation_method": "ratio",
    },
    {
        "metric_key": "coaching_uplift_avg",
        "display_name": "Average Coaching Uplift",
        "description": "Average score delta after a coaching intervention.",
        "entity_type": "manager",
        "aggregation_method": "avg",
    },
    {
        "metric_key": "manager_override_delta",
        "display_name": "Manager Override Delta",
        "description": "Average delta between AI score and manager override.",
        "entity_type": "manager",
        "aggregation_method": "avg",
    },
]

CLOSE_ATTEMPT_HINTS = (
    "today",
    "schedule",
    "get started",
    "sign up",
    "move forward",
    "next step",
    "book",
)

MATERIALIZED_PERIODS = ("7", "30", "90")
PARTITIONED_TABLES = (
    "sessions",
    "session_turns",
    "session_events",
    "analytics_fact_sessions",
    "analytics_metric_snapshots",
    "analytics_materialized_views",
)
DISAGREEMENT_THRESHOLD = 2.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _week_start(day_value: date) -> date:
    return day_value - timedelta(days=day_value.weekday())


def _month_start(value: datetime) -> datetime:
    normalized = _normalize_dt(value) or _utcnow()
    return normalized.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_month(value: datetime, offset: int) -> datetime:
    year = value.year
    month = value.month + offset
    while month <= 0:
        year -= 1
        month += 12
    while month > 12:
        year += 1
        month -= 12
    return value.replace(year=year, month=month, day=1)


def _period_bounds(period_key: str, *, now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    days = int(period_key)
    current_end = _normalize_dt(now) or _utcnow()
    current_start = current_end - timedelta(days=days)
    previous_end = current_start
    previous_start = previous_end - max(timedelta(days=1), current_end - current_start)
    return current_start, current_end, previous_start, previous_end


def _word_count(text: str | None) -> int:
    if not text:
        return 0
    return len([chunk for chunk in text.strip().split() if chunk])


def _score_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("score")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


class AnalyticsRefreshService:
    def __init__(self) -> None:
        self.management_analytics = ManagementAnalyticsService(prefer_materialized_views=False)

    def ensure_metric_definitions(self, db: Session) -> int:
        created = 0
        for payload in METRIC_DEFINITIONS:
            row = db.get(AnalyticsMetricDefinition, payload["metric_key"])
            if row is None:
                row = AnalyticsMetricDefinition(**payload)
                db.add(row)
                created += 1
                continue
            row.display_name = payload["display_name"]
            row.description = payload["description"]
            row.entity_type = payload["entity_type"]
            row.aggregation_method = payload["aggregation_method"]
            row.active = True
        return created

    def _payload_row_count(self, payload: dict[str, Any]) -> int:
        for key in ("items", "alerts_preview", "score_trend", "scenario_pass_matrix", "coaching_uplift"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        summary = payload.get("summary")
        if isinstance(summary, dict):
            return len(summary)
        return len(payload)

    def _upsert_materialized_view(
        self,
        db: Session,
        *,
        manager_id: str,
        view_name: str,
        period_key: str,
        window_start: datetime,
        window_end: datetime,
        payload: dict[str, Any],
        refreshed_at: datetime,
        run_id: str | None,
    ) -> None:
        row = db.scalar(
            select(AnalyticsMaterializedView).where(
                AnalyticsMaterializedView.manager_id == manager_id,
                AnalyticsMaterializedView.view_name == view_name,
                AnalyticsMaterializedView.period_key == period_key,
            )
        )
        if row is None:
            row = AnalyticsMaterializedView(
                manager_id=manager_id,
                view_name=view_name,
                period_key=period_key,
                window_start=window_start,
                window_end=window_end,
                payload_json=payload,
                row_count=self._payload_row_count(payload),
                refreshed_at=refreshed_at,
                source_refresh_run_id=run_id,
            )
            db.add(row)
            return
        row.window_start = window_start
        row.window_end = window_end
        row.payload_json = payload
        row.row_count = self._payload_row_count(payload)
        row.refreshed_at = refreshed_at
        row.source_refresh_run_id = run_id

    def _refresh_materialized_views(self, db: Session, *, manager_id: str, run_id: str | None) -> dict[str, int]:
        refreshed_at = _utcnow()
        stored = 0
        for period_key in MATERIALIZED_PERIODS:
            current_start, current_end, previous_start, previous_end = _period_bounds(period_key, now=refreshed_at)
            payloads = {
                "command_center": self.management_analytics.get_command_center(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                    previous_start=previous_start,
                    previous_end=previous_end,
                    period=period_key,
                ),
                "scenario_intelligence": self.management_analytics.get_scenario_intelligence(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                    period=period_key,
                ),
                "coaching_analytics": self.management_analytics.get_coaching_analytics(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                    period=period_key,
                ),
                "benchmarks": self.management_analytics.get_benchmarks(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                    period=period_key,
                ),
                "alerts": self.management_analytics.get_alerts(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                    period=period_key,
                ),
            }
            for view_name, payload in payloads.items():
                self._upsert_materialized_view(
                    db,
                    manager_id=manager_id,
                    view_name=view_name,
                    period_key=period_key,
                    window_start=current_start,
                    window_end=current_end,
                    payload=payload,
                    refreshed_at=refreshed_at,
                    run_id=run_id,
                )
                stored += 1
        return {"materialized_view_rows": stored}

    def ensure_partition_windows(self, db: Session, *, months_back: int = 3, months_forward: int = 6) -> dict[str, int]:
        backend = getattr(getattr(db, "bind", None), "dialect", None)
        backend_name = getattr(backend, "name", "logical") or "logical"
        now = _utcnow()
        base = _month_start(now)
        ensured = 0
        for table_name in PARTITIONED_TABLES:
            for offset in range(-months_back, months_forward + 1):
                start = _shift_month(base, offset)
                end = _shift_month(base, offset + 1)
                partition_key = f"{start.year:04d}_{start.month:02d}"
                status = "active"
                if start > now:
                    status = "upcoming"
                elif end <= now:
                    status = "retained"

                row = db.scalar(
                    select(AnalyticsPartitionWindow).where(
                        AnalyticsPartitionWindow.table_name == table_name,
                        AnalyticsPartitionWindow.partition_key == partition_key,
                    )
                )
                metadata = {
                    "strategy": "monthly-range",
                    "physical_partitioning": backend_name == "postgresql",
                }
                if row is None:
                    row = AnalyticsPartitionWindow(
                        table_name=table_name,
                        partition_key=partition_key,
                        backend=backend_name if backend_name == "postgresql" else "logical",
                        status=status,
                        range_start=start,
                        range_end=end,
                        metadata_json=metadata,
                    )
                    db.add(row)
                    ensured += 1
                    continue
                row.backend = backend_name if backend_name == "postgresql" else "logical"
                row.status = status
                row.range_start = start
                row.range_end = end
                row.metadata_json = metadata
        return {"partition_window_rows": ensured}

    def _start_run(self, db: Session, *, scope_type: str, scope_id: str | None) -> AnalyticsRefreshRun:
        row = AnalyticsRefreshRun(
            scope_type=scope_type,
            scope_id=scope_id,
            status="running",
            row_counts_json={},
            started_at=_utcnow(),
        )
        db.add(row)
        db.flush()
        return row

    def _finish_run(
        self,
        db: Session,
        *,
        run: AnalyticsRefreshRun,
        status: str,
        row_counts: dict[str, Any],
        error: str | None = None,
    ) -> None:
        run.status = status
        run.row_counts_json = row_counts
        run.error = error
        run.completed_at = _utcnow()

    def _session_bundle(self, db: Session, *, session_id: str) -> tuple[DrillSession, Assignment, User, User, Scenario]:
        row = db.execute(
            select(DrillSession, Assignment, User, Scenario)
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .join(User, User.id == DrillSession.rep_id)
            .join(Scenario, Scenario.id == DrillSession.scenario_id)
            .where(DrillSession.id == session_id)
        ).first()
        if row is None:
            raise ValueError("session not found for analytics refresh")
        session, assignment, rep, scenario = row
        manager = db.scalar(select(User).where(User.id == assignment.assigned_by))
        if manager is None:
            raise ValueError("manager not found for analytics refresh")
        return session, assignment, rep, manager, scenario

    def _upsert_manager_dim(self, db: Session, *, manager: User, team: Team | None) -> None:
        row = db.get(AnalyticsDimManager, manager.id)
        if row is None:
            row = AnalyticsDimManager(
                manager_id=manager.id,
                org_id=manager.org_id,
                team_id=team.id if team else manager.team_id,
                manager_name=manager.name,
                manager_email=manager.email,
            )
            db.add(row)
        row.org_id = manager.org_id
        row.team_id = team.id if team else manager.team_id
        row.manager_name = manager.name
        row.manager_email = manager.email
        row.last_refreshed_at = _utcnow()

    def _upsert_rep_dim(self, db: Session, *, rep: User, manager_id: str, first_session_at: datetime | None, last_session_at: datetime | None) -> None:
        row = db.get(AnalyticsDimRep, rep.id)
        if row is None:
            row = AnalyticsDimRep(
                rep_id=rep.id,
                manager_id=manager_id,
                org_id=rep.org_id,
                team_id=rep.team_id,
                rep_name=rep.name,
                rep_email=rep.email,
            )
            db.add(row)
        row.manager_id = manager_id
        row.org_id = rep.org_id
        row.team_id = rep.team_id
        row.rep_name = rep.name
        row.rep_email = rep.email
        row.first_session_at = first_session_at
        row.last_session_at = last_session_at
        row.last_refreshed_at = _utcnow()

    def _upsert_team_dim(
        self,
        db: Session,
        *,
        team: Team,
        manager: User,
        last_session_at: datetime | None,
    ) -> None:
        row = db.get(AnalyticsDimTeam, team.id)
        if row is None:
            row = AnalyticsDimTeam(
                team_id=team.id,
                org_id=team.org_id,
                manager_id=manager.id,
                team_name=team.name,
            )
            db.add(row)
        row.org_id = team.org_id
        row.manager_id = manager.id
        row.team_name = team.name
        row.manager_name = manager.name
        row.rep_count = db.scalar(
            select(func.count(User.id)).where(User.team_id == team.id, User.role == UserRole.REP)
        ) or 0
        row.last_session_at = last_session_at
        row.last_refreshed_at = _utcnow()

    def _upsert_scenario_dim(self, db: Session, *, scenario: Scenario) -> None:
        row = db.get(AnalyticsDimScenario, scenario.id)
        if row is None:
            row = AnalyticsDimScenario(
                scenario_id=scenario.id,
                org_id=scenario.org_id,
                name=scenario.name,
                industry=scenario.industry,
                difficulty=scenario.difficulty,
                stage_count=len(scenario.stages or []),
            )
            db.add(row)
        row.org_id = scenario.org_id
        row.name = scenario.name
        row.industry = scenario.industry
        row.difficulty = scenario.difficulty
        row.stage_count = len(scenario.stages or [])
        row.last_refreshed_at = _utcnow()

    def _ensure_time_dim(self, db: Session, *, day_value: date) -> None:
        row = db.get(AnalyticsDimTime, day_value)
        iso_year, iso_week, _ = day_value.isocalendar()
        week_start = _week_start(day_value)
        month_start = day_value.replace(day=1)
        if row is None:
            row = AnalyticsDimTime(
                day_date=day_value,
                week_start=week_start,
                month_start=month_start,
                year=day_value.year,
                quarter=((day_value.month - 1) // 3) + 1,
                month=day_value.month,
                day_of_month=day_value.day,
                day_of_week=day_value.weekday(),
                iso_year=iso_year,
                iso_week=iso_week,
                is_weekend=day_value.weekday() >= 5,
            )
            db.add(row)
            return
        row.week_start = week_start
        row.month_start = month_start
        row.year = day_value.year
        row.quarter = ((day_value.month - 1) // 3) + 1
        row.month = day_value.month
        row.day_of_month = day_value.day
        row.day_of_week = day_value.weekday()
        row.iso_year = iso_year
        row.iso_week = iso_week
        row.is_weekend = day_value.weekday() >= 5

    def _first_response_latency_ms(self, events: list[SessionEvent]) -> int | None:
        first_client = None
        first_server = None
        for event in sorted(events, key=lambda item: (item.event_ts, item.sequence)):
            if first_client is None and event.event_type == "client.audio.chunk":
                first_client = _normalize_dt(event.event_ts)
            if first_server is None and event.event_type == "server.ai.audio.chunk":
                first_server = _normalize_dt(event.event_ts)
            if first_client and first_server:
                break
        if first_client is None or first_server is None:
            return None
        return max(0, int((first_server - first_client).total_seconds() * 1000))

    def _session_metrics(
        self,
        *,
        session: DrillSession,
        scorecard: Scorecard | None,
        turns: list[SessionTurn],
        events: list[SessionEvent],
        reviews: list[ManagerReview],
        coaching_notes: list[ManagerCoachingNote],
        scenario: Scenario,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        rep_turns = [turn for turn in turns if turn.speaker == TurnSpeaker.REP]
        ai_turns = [turn for turn in turns if turn.speaker == TurnSpeaker.AI]
        rep_word_count = sum(_word_count(turn.text) for turn in rep_turns)
        ai_word_count = sum(_word_count(turn.text) for turn in ai_turns)
        turn_count = len(turns)
        objection_counter: Counter[str] = Counter()
        objection_turn_count = 0
        for turn in turns:
            tags = turn.objection_tags or []
            if tags:
                objection_turn_count += 1
            for tag in tags:
                objection_counter[tag] += 1
        barge_in_count = sum(
            1
            for event in events
            if event.event_type == "server.session.state" and isinstance(event.payload, dict) and event.payload.get("state") == "barge_in_detected"
        )
        first_response_latency_ms = self._first_response_latency_ms(events)
        talk_ratio = round(rep_word_count / max(1, rep_word_count + ai_word_count), 3) if (rep_word_count + ai_word_count) else None
        close_attempt_count = sum(
            1
            for turn in rep_turns
            if any(hint in (turn.text or "").lower() for hint in CLOSE_ATTEMPT_HINTS)
        )
        opening_score = _score_value((scorecard.category_scores if scorecard else {}).get("opening"))
        pitch_score = _score_value((scorecard.category_scores if scorecard else {}).get("pitch")) or _score_value((scorecard.category_scores if scorecard else {}).get("pitch_delivery"))
        objection_score = _score_value((scorecard.category_scores if scorecard else {}).get("objection_handling"))
        closing_score = _score_value((scorecard.category_scores if scorecard else {}).get("closing")) or _score_value((scorecard.category_scores if scorecard else {}).get("closing_technique"))
        professionalism_score = _score_value((scorecard.category_scores if scorecard else {}).get("professionalism"))
        overall_score = scorecard.overall_score if scorecard else None
        difficulty_adjusted = None
        if overall_score is not None:
            difficulty_adjusted = round(overall_score - max(0, scenario.difficulty - 1) * 0.2, 2)

        session_day = (_normalize_dt(session.started_at) or _utcnow()).date()
        session_week_start = _week_start(session_day)
        latest_reviewed_at = max((_normalize_dt(review.reviewed_at) for review in reviews), default=None)
        latest_coaching_note_at = max((_normalize_dt(note.created_at) for note in coaching_notes), default=None)

        fact_session = {
            "session_id": session.id,
            "assignment_id": session.assignment_id,
            "manager_id": "",  # set by caller
            "rep_id": session.rep_id,
            "org_id": "",
            "team_id": None,
            "scenario_id": session.scenario_id,
            "session_date": session_day,
            "week_start": session_week_start,
            "started_at": _normalize_dt(session.started_at),
            "ended_at": _normalize_dt(session.ended_at),
            "duration_seconds": session.duration_seconds,
            "status": session.status.value,
            "difficulty": scenario.difficulty,
            "overall_score": overall_score,
            "difficulty_adjusted_score": difficulty_adjusted,
            "pass_flag": bool(overall_score is not None and overall_score >= 7.0),
            "opening_score": opening_score,
            "pitch_score": pitch_score,
            "objection_score": objection_score,
            "closing_score": closing_score,
            "professionalism_score": professionalism_score,
            "turn_count": turn_count,
            "rep_turn_count": len(rep_turns),
            "ai_turn_count": len(ai_turns),
            "rep_word_count": rep_word_count,
            "ai_word_count": ai_word_count,
            "talk_ratio": talk_ratio,
            "barge_in_count": barge_in_count,
            "objection_turn_count": objection_turn_count,
            "close_attempt_count": close_attempt_count,
            "weak_area_count": len(scorecard.weakness_tags if scorecard else []),
            "manager_reviewed": bool(reviews),
            "coaching_note_count": len(coaching_notes),
            "latest_reviewed_at": latest_reviewed_at,
            "latest_coaching_note_at": latest_coaching_note_at,
            "weakness_tags_json": list(scorecard.weakness_tags if scorecard else []),
            "objection_tags_json": [tag for tag, _ in objection_counter.most_common()],
        }
        turn_metrics = {
            "session_id": session.id,
            "manager_id": "",  # set by caller
            "rep_id": session.rep_id,
            "session_date": session_day,
            "average_rep_turn_words": round(rep_word_count / len(rep_turns), 2) if rep_turns else None,
            "average_ai_turn_words": round(ai_word_count / len(ai_turns), 2) if ai_turns else None,
            "longest_rep_turn_words": max((_word_count(turn.text) for turn in rep_turns), default=0),
            "longest_ai_turn_words": max((_word_count(turn.text) for turn in ai_turns), default=0),
            "first_response_latency_ms": first_response_latency_ms,
            "interruption_count": barge_in_count,
            "objection_tag_counts_json": dict(objection_counter),
        }
        return fact_session, turn_metrics

    def _upsert_session_fact(self, db: Session, *, payload: dict[str, Any]) -> None:
        row = db.get(AnalyticsFactSession, payload["session_id"])
        if row is None:
            row = AnalyticsFactSession(**payload)
            db.add(row)
            return
        for key, value in payload.items():
            setattr(row, key, value)

    def _upsert_turn_metrics(self, db: Session, *, payload: dict[str, Any]) -> None:
        row = db.get(AnalyticsFactSessionTurnMetrics, payload["session_id"])
        if row is None:
            row = AnalyticsFactSessionTurnMetrics(**payload)
            db.add(row)
            return
        for key, value in payload.items():
            setattr(row, key, value)

    def _rebuild_rep_aggregates(self, db: Session, *, manager_id: str, rep_id: str, team_id: str | None) -> dict[str, int]:
        rows = db.scalars(
            select(AnalyticsFactSession)
            .where(AnalyticsFactSession.manager_id == manager_id, AnalyticsFactSession.rep_id == rep_id)
            .order_by(AnalyticsFactSession.started_at.asc())
        ).all()

        db.execute(delete(AnalyticsFactRepDay).where(AnalyticsFactRepDay.manager_id == manager_id, AnalyticsFactRepDay.rep_id == rep_id))
        db.execute(delete(AnalyticsFactRepWeek).where(AnalyticsFactRepWeek.manager_id == manager_id, AnalyticsFactRepWeek.rep_id == rep_id))

        day_groups: dict[date, list[AnalyticsFactSession]] = defaultdict(list)
        week_groups: dict[date, list[AnalyticsFactSession]] = defaultdict(list)
        for row in rows:
            day_groups[row.session_date].append(row)
            week_groups[row.week_start].append(row)

        day_count = 0
        for day_date, items in day_groups.items():
            self._ensure_time_dim(db, day_value=day_date)
            scored = [item for item in items if item.overall_score is not None]
            weak_tags = Counter(tag for item in items for tag in item.weakness_tags_json or [])
            db.add(
                AnalyticsFactRepDay(
                    manager_id=manager_id,
                    rep_id=rep_id,
                    team_id=team_id,
                    day_date=day_date,
                    session_count=len(items),
                    scored_session_count=len(scored),
                    average_score=round(sum(item.overall_score for item in scored if item.overall_score is not None) / len(scored), 2) if scored else None,
                    pass_rate=round(sum(1 for item in scored if item.pass_flag) / len(scored), 3) if scored else None,
                    review_coverage_rate=round(sum(1 for item in scored if item.manager_reviewed) / len(scored), 3) if scored else None,
                    average_duration_seconds=round(sum(item.duration_seconds or 0 for item in items) / len(items), 2) if items else None,
                    average_talk_ratio=round(sum(item.talk_ratio or 0 for item in items if item.talk_ratio is not None) / max(1, len([item for item in items if item.talk_ratio is not None])), 3) if items else None,
                    average_barge_in_count=round(sum(item.barge_in_count for item in items) / len(items), 2) if items else None,
                    average_close_attempts=round(sum(item.close_attempt_count for item in items) / len(items), 2) if items else None,
                    weak_area_tags_json=[tag for tag, _ in weak_tags.most_common(5)],
                )
            )
            day_count += 1

        week_count = 0
        for week_start, items in week_groups.items():
            self._ensure_time_dim(db, day_value=week_start)
            scored = [item for item in items if item.overall_score is not None]
            scores = [item.overall_score for item in scored if item.overall_score is not None]
            weak_tags = Counter(tag for item in items for tag in item.weakness_tags_json or [])
            db.add(
                AnalyticsFactRepWeek(
                    manager_id=manager_id,
                    rep_id=rep_id,
                    team_id=team_id,
                    week_start=week_start,
                    session_count=len(items),
                    scored_session_count=len(scored),
                    average_score=round(sum(scores) / len(scores), 2) if scores else None,
                    pass_rate=round(sum(1 for item in scored if item.pass_flag) / len(scored), 3) if scored else None,
                    review_coverage_rate=round(sum(1 for item in scored if item.manager_reviewed) / len(scored), 3) if scored else None,
                    score_delta=round(scores[-1] - scores[0], 2) if len(scores) >= 2 else None,
                    score_volatility=round(pstdev(scores), 2) if len(scores) >= 2 else None,
                    weak_area_tags_json=[tag for tag, _ in weak_tags.most_common(5)],
                )
            )
            week_count += 1
        return {"rep_day_rows": day_count, "rep_week_rows": week_count}

    def _rebuild_team_aggregates(self, db: Session, *, manager_id: str, team_id: str | None) -> dict[str, int]:
        session_rows = db.scalars(
            select(AnalyticsFactSession).where(AnalyticsFactSession.manager_id == manager_id).order_by(AnalyticsFactSession.session_date.asc())
        ).all()
        db.execute(delete(AnalyticsFactTeamDay).where(AnalyticsFactTeamDay.manager_id == manager_id))

        assignment_rows = db.execute(
            select(Assignment.created_at, Assignment.status)
            .where(Assignment.assigned_by == manager_id)
            .order_by(Assignment.created_at.asc())
        ).all()
        assignment_groups: dict[date, list[Any]] = defaultdict(list)
        for created_at, status in assignment_rows:
            created = _normalize_dt(created_at)
            if created is None:
                continue
            assignment_groups[created.date()].append(status)

        session_groups: dict[date, list[AnalyticsFactSession]] = defaultdict(list)
        for row in session_rows:
            session_groups[row.session_date].append(row)

        count = 0
        for day_date in sorted(set(session_groups) | set(assignment_groups)):
            self._ensure_time_dim(db, day_value=day_date)
            items = session_groups.get(day_date, [])
            scored = [item for item in items if item.overall_score is not None]
            statuses = assignment_groups.get(day_date, [])
            db.add(
                AnalyticsFactTeamDay(
                    manager_id=manager_id,
                    team_id=team_id,
                    day_date=day_date,
                    assignment_count=len(statuses),
                    completed_assignment_count=sum(1 for status in statuses if status == AssignmentStatus.COMPLETED),
                    session_count=len(items),
                    scored_session_count=len(scored),
                    active_rep_count=len({item.rep_id for item in items}),
                    average_score=round(sum(item.overall_score for item in scored if item.overall_score is not None) / len(scored), 2) if scored else None,
                    completion_rate=round(sum(1 for status in statuses if status == AssignmentStatus.COMPLETED) / len(statuses), 3) if statuses else None,
                    review_coverage_rate=round(sum(1 for item in scored if item.manager_reviewed) / len(scored), 3) if scored else None,
                    red_flag_count=sum(1 for item in scored if (item.overall_score or 0) < 6.0),
                )
            )
            count += 1
        return {"team_day_rows": count}

    def _rebuild_scenario_aggregates(self, db: Session, *, manager_id: str, scenario_id: str) -> dict[str, int]:
        rows = db.scalars(
            select(AnalyticsFactSession)
            .where(AnalyticsFactSession.manager_id == manager_id, AnalyticsFactSession.scenario_id == scenario_id)
            .order_by(AnalyticsFactSession.session_date.asc())
        ).all()
        db.execute(
            delete(AnalyticsFactScenarioDay).where(
                AnalyticsFactScenarioDay.manager_id == manager_id,
                AnalyticsFactScenarioDay.scenario_id == scenario_id,
            )
        )
        groups: dict[date, list[AnalyticsFactSession]] = defaultdict(list)
        for row in rows:
            groups[row.session_date].append(row)

        count = 0
        for day_date, items in groups.items():
            self._ensure_time_dim(db, day_value=day_date)
            scored = [item for item in items if item.overall_score is not None]
            weak_tags = Counter(tag for item in items for tag in item.weakness_tags_json or [])
            objection_tags = Counter(tag for item in items for tag in item.objection_tags_json or [])
            db.add(
                AnalyticsFactScenarioDay(
                    manager_id=manager_id,
                    scenario_id=scenario_id,
                    day_date=day_date,
                    difficulty=items[0].difficulty if items else 1,
                    session_count=len(items),
                    scored_session_count=len(scored),
                    rep_count=len({item.rep_id for item in items}),
                    average_score=round(sum(item.overall_score for item in scored if item.overall_score is not None) / len(scored), 2) if scored else None,
                    pass_rate=round(sum(1 for item in scored if item.pass_flag) / len(scored), 3) if scored else None,
                    average_duration_seconds=round(sum(item.duration_seconds or 0 for item in items) / len(items), 2) if items else None,
                    average_barge_in_count=round(sum(item.barge_in_count for item in items) / len(items), 2) if items else None,
                    top_weakness_tags_json=[tag for tag, _ in weak_tags.most_common(5)],
                    top_objection_tags_json=[tag for tag, _ in objection_tags.most_common(5)],
                )
            )
            count += 1
        return {"scenario_day_rows": count}

    def _rebuild_coaching_interventions(self, db: Session, *, manager_id: str, rep_id: str | None = None) -> dict[str, int]:
        query = (
            select(ManagerCoachingNote, Scorecard, DrillSession, Assignment)
            .join(Scorecard, Scorecard.id == ManagerCoachingNote.scorecard_id)
            .join(DrillSession, DrillSession.id == Scorecard.session_id)
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .where(Assignment.assigned_by == manager_id)
            .order_by(ManagerCoachingNote.created_at.asc())
        )
        if rep_id:
            query = query.where(DrillSession.rep_id == rep_id)
        rows = db.execute(query).all()

        if rep_id:
            db.execute(
                delete(AnalyticsFactCoachingIntervention).where(
                    AnalyticsFactCoachingIntervention.manager_id == manager_id,
                    AnalyticsFactCoachingIntervention.rep_id == rep_id,
                )
            )
        else:
            db.execute(delete(AnalyticsFactCoachingIntervention).where(AnalyticsFactCoachingIntervention.manager_id == manager_id))

        future_sessions = db.scalars(
            select(AnalyticsFactSession)
            .where(AnalyticsFactSession.manager_id == manager_id)
            .order_by(AnalyticsFactSession.started_at.asc())
        ).all()
        sessions_by_rep: dict[str, list[AnalyticsFactSession]] = defaultdict(list)
        for row in future_sessions:
            sessions_by_rep[row.rep_id].append(row)

        count = 0
        for note, scorecard, source_session, _ in rows:
            rep_sessions = sessions_by_rep.get(source_session.rep_id, [])
            note_created = _normalize_dt(note.created_at) or _utcnow()
            next_session = next(
                (
                    row
                    for row in rep_sessions
                    if row.session_id != source_session.id
                    and _normalize_dt(row.started_at)
                    and (_normalize_dt(row.started_at) or _utcnow()) > note_created
                    and row.overall_score is not None
                ),
                None,
            )
            db.add(
                AnalyticsFactCoachingIntervention(
                    coaching_note_id=note.id,
                    manager_id=manager_id,
                    reviewer_id=note.reviewer_id,
                    rep_id=source_session.rep_id,
                    scorecard_id=scorecard.id,
                    session_id=source_session.id,
                    next_session_id=next_session.session_id if next_session else None,
                    note_created_at=note_created,
                    visible_to_rep=note.visible_to_rep,
                    before_score=scorecard.overall_score,
                    after_score=next_session.overall_score if next_session else None,
                    score_delta=round((next_session.overall_score or 0) - scorecard.overall_score, 2) if next_session and next_session.overall_score is not None else None,
                    weakness_tags_json=list(note.weakness_tags or []),
                )
            )
            count += 1
        return {"coaching_rows": count}

    def _rebuild_manager_calibration(self, db: Session, *, manager_id: str) -> dict[str, int]:
        rows = db.execute(
            select(ManagerReview, Scorecard, DrillSession, Assignment)
            .join(Scorecard, Scorecard.id == ManagerReview.scorecard_id)
            .join(DrillSession, DrillSession.id == Scorecard.session_id)
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .where(Assignment.assigned_by == manager_id)
            .order_by(ManagerReview.reviewed_at.asc())
        ).all()

        db.execute(delete(AnalyticsFactManagerCalibration).where(AnalyticsFactManagerCalibration.manager_id == manager_id))
        count = 0
        for review, scorecard, source_session, _ in rows:
            delta = None
            if review.override_score is not None and scorecard.overall_score is not None:
                delta = round(review.override_score - scorecard.overall_score, 2)
            db.add(
                AnalyticsFactManagerCalibration(
                    review_id=review.id,
                    manager_id=manager_id,
                    reviewer_id=review.reviewer_id,
                    scorecard_id=scorecard.id,
                    session_id=source_session.id,
                    reviewed_at=_normalize_dt(review.reviewed_at) or _utcnow(),
                    ai_score=scorecard.overall_score,
                    override_score=review.override_score,
                    delta_score=delta,
                    reason_code=review.reason_code.value,
                )
            )
            count += 1
        return {"calibration_rows": count}

    def _upsert_metric_snapshot(
        self,
        db: Session,
        *,
        metric_key: str,
        entity_type: str,
        entity_id: str,
        manager_id: str | None,
        snapshot_date: date,
        value_numeric: float | None,
        value_json: dict[str, Any] | None = None,
    ) -> None:
        row = db.scalar(
            select(AnalyticsMetricSnapshot).where(
                AnalyticsMetricSnapshot.metric_key == metric_key,
                AnalyticsMetricSnapshot.entity_type == entity_type,
                AnalyticsMetricSnapshot.entity_id == entity_id,
                AnalyticsMetricSnapshot.snapshot_date == snapshot_date,
            )
        )
        if row is None:
            row = AnalyticsMetricSnapshot(
                metric_key=metric_key,
                entity_type=entity_type,
                entity_id=entity_id,
                manager_id=manager_id,
                snapshot_date=snapshot_date,
                value_numeric=value_numeric,
                value_json=value_json or {},
            )
            db.add(row)
            return
        row.manager_id = manager_id
        row.value_numeric = value_numeric
        row.value_json = value_json or {}

    def _refresh_metric_snapshots(self, db: Session, *, manager_id: str, snapshot_date: date) -> dict[str, int]:
        session_rows = db.scalars(select(AnalyticsFactSession).where(AnalyticsFactSession.manager_id == manager_id)).all()
        team_rows = db.scalars(select(AnalyticsFactTeamDay).where(AnalyticsFactTeamDay.manager_id == manager_id)).all()
        calibration_rows = db.scalars(
            select(AnalyticsFactManagerCalibration).where(AnalyticsFactManagerCalibration.manager_id == manager_id)
        ).all()
        coaching_rows = db.scalars(
            select(AnalyticsFactCoachingIntervention).where(AnalyticsFactCoachingIntervention.manager_id == manager_id)
        ).all()

        scored = [row for row in session_rows if row.overall_score is not None]
        rep_groups: dict[str, list[AnalyticsFactSession]] = defaultdict(list)
        scenario_groups: dict[str, list[AnalyticsFactSession]] = defaultdict(list)
        for row in session_rows:
            rep_groups[row.rep_id].append(row)
            scenario_groups[row.scenario_id].append(row)

        reps_at_risk = 0
        for rep_rows in rep_groups.values():
            rep_scored = [row.overall_score for row in rep_rows if row.overall_score is not None]
            if not rep_scored:
                continue
            average = sum(rep_scored) / len(rep_scored)
            delta = rep_scored[-1] - rep_scored[0] if len(rep_scored) >= 2 else 0.0
            if average < 6.5 or delta < -0.5:
                reps_at_risk += 1

        assignment_count = sum(row.assignment_count for row in team_rows)
        completed_count = sum(row.completed_assignment_count for row in team_rows)
        review_coverage = round(sum(1 for row in scored if row.manager_reviewed) / len(scored), 3) if scored else None

        self._upsert_metric_snapshot(
            db,
            metric_key="team_average_score",
            entity_type="team",
            entity_id=manager_id,
            manager_id=manager_id,
            snapshot_date=snapshot_date,
            value_numeric=round(sum(row.overall_score for row in scored if row.overall_score is not None) / len(scored), 2) if scored else None,
        )
        self._upsert_metric_snapshot(
            db,
            metric_key="completion_rate",
            entity_type="team",
            entity_id=manager_id,
            manager_id=manager_id,
            snapshot_date=snapshot_date,
            value_numeric=round(completed_count / assignment_count, 3) if assignment_count else None,
            value_json={"assignment_count": assignment_count, "completed_assignment_count": completed_count},
        )
        self._upsert_metric_snapshot(
            db,
            metric_key="review_coverage_rate",
            entity_type="team",
            entity_id=manager_id,
            manager_id=manager_id,
            snapshot_date=snapshot_date,
            value_numeric=review_coverage,
        )
        self._upsert_metric_snapshot(
            db,
            metric_key="reps_at_risk",
            entity_type="team",
            entity_id=manager_id,
            manager_id=manager_id,
            snapshot_date=snapshot_date,
            value_numeric=float(reps_at_risk),
        )
        self._upsert_metric_snapshot(
            db,
            metric_key="coaching_uplift_avg",
            entity_type="manager",
            entity_id=manager_id,
            manager_id=manager_id,
            snapshot_date=snapshot_date,
            value_numeric=round(sum(row.score_delta for row in coaching_rows if row.score_delta is not None) / len([row for row in coaching_rows if row.score_delta is not None]), 2) if [row for row in coaching_rows if row.score_delta is not None] else None,
        )
        self._upsert_metric_snapshot(
            db,
            metric_key="manager_override_delta",
            entity_type="manager",
            entity_id=manager_id,
            manager_id=manager_id,
            snapshot_date=snapshot_date,
            value_numeric=round(sum(row.delta_score for row in calibration_rows if row.delta_score is not None) / len([row for row in calibration_rows if row.delta_score is not None]), 2) if [row for row in calibration_rows if row.delta_score is not None] else None,
        )

        for scenario_id, items in scenario_groups.items():
            scenario_scored = [row for row in items if row.overall_score is not None]
            self._upsert_metric_snapshot(
                db,
                metric_key="scenario_pass_rate",
                entity_type="scenario",
                entity_id=scenario_id,
                manager_id=manager_id,
                snapshot_date=snapshot_date,
                value_numeric=round(sum(1 for row in scenario_scored if row.pass_flag) / len(scenario_scored), 3) if scenario_scored else None,
                value_json={"session_count": len(items), "scored_session_count": len(scenario_scored)},
            )
        return {
            "metric_snapshots": 6 + len(scenario_groups),
        }

    def _refresh_alert_facts(self, db: Session, *, manager_id: str) -> dict[str, int]:
        manager = db.get(User, manager_id)
        if manager is None:
            return {"alert_rows": 0}

        refreshed_at = _utcnow()
        existing_first_seen = {
            (row.period_key, row.alert_key): _normalize_dt(row.first_seen_at) or refreshed_at
            for row in db.scalars(
                select(AnalyticsFactAlert).where(AnalyticsFactAlert.manager_id == manager_id)
            ).all()
        }
        db.execute(delete(AnalyticsFactAlert).where(AnalyticsFactAlert.manager_id == manager_id))

        inserted = 0
        inserted_keys: set[tuple[str, str]] = set()
        for period_key in MATERIALIZED_PERIODS:
            current_start, current_end, previous_start, previous_end = _period_bounds(period_key, now=refreshed_at)
            command_center = self.management_analytics.get_command_center(
                db,
                manager_id=manager_id,
                date_from=current_start,
                date_to=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                period=period_key,
            )
            for item in command_center.get("alerts", []):
                occurred_at = _normalize_dt(datetime.fromisoformat(item["occurred_at"])) or refreshed_at
                db.add(
                    AnalyticsFactAlert(
                        alert_key=item["id"],
                        manager_id=manager_id,
                        org_id=manager.org_id,
                        team_id=manager.team_id,
                        period_key=period_key,
                        severity=item["severity"],
                        kind=item["kind"],
                        title=item["title"],
                        description=item["description"],
                        occurred_at=occurred_at,
                        rep_id=item.get("rep_id"),
                        scenario_id=item.get("scenario_id"),
                        session_id=item.get("session_id"),
                        focus_turn_id=item.get("focus_turn_id"),
                        baseline_value=item.get("baseline_value"),
                        observed_value=item.get("observed_value"),
                        delta=item.get("delta"),
                        z_score=item.get("z_score"),
                        is_active=True,
                        first_seen_at=existing_first_seen.get((period_key, item["id"]), refreshed_at),
                        last_seen_at=refreshed_at,
                        metadata_json={
                            "rep_name": item.get("rep_name"),
                            **(item.get("metadata") or {}),
                        },
                    )
                )
                inserted_keys.add((period_key, item["id"]))
                inserted += 1
            for item in self._grading_disagreement_alert_items(
                db,
                manager_id=manager_id,
                period_key=period_key,
                date_from=current_start,
                date_to=current_end,
                refreshed_at=refreshed_at,
            ):
                if (period_key, item["id"]) in inserted_keys:
                    continue
                db.add(
                    AnalyticsFactAlert(
                        alert_key=item["id"],
                        manager_id=manager_id,
                        org_id=manager.org_id,
                        team_id=item.get("team_id") or manager.team_id,
                        period_key=period_key,
                        severity=item["severity"],
                        kind=item["kind"],
                        title=item["title"],
                        description=item["description"],
                        occurred_at=item["occurred_at"],
                        rep_id=item.get("rep_id"),
                        scenario_id=item.get("scenario_id"),
                        session_id=item.get("session_id"),
                        focus_turn_id=None,
                        baseline_value=item.get("baseline_value"),
                        observed_value=item.get("observed_value"),
                        delta=item.get("delta"),
                        z_score=None,
                        is_active=True,
                        first_seen_at=existing_first_seen.get((period_key, item["id"]), refreshed_at),
                        last_seen_at=refreshed_at,
                        metadata_json=item.get("metadata") or {},
                    )
                )
                inserted += 1
        return {"alert_rows": inserted}

    def _grading_disagreement_alert_items(
        self,
        db: Session,
        *,
        manager_id: str,
        period_key: str,
        date_from: datetime,
        date_to: datetime,
        refreshed_at: datetime,
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(AnalyticsFactManagerCalibration)
            .where(
                AnalyticsFactManagerCalibration.manager_id == manager_id,
                AnalyticsFactManagerCalibration.reviewed_at >= date_from,
                AnalyticsFactManagerCalibration.reviewed_at <= date_to,
            )
            .order_by(AnalyticsFactManagerCalibration.reviewed_at.desc())
        ).all()

        items: list[dict[str, Any]] = []
        for row in rows:
            delta = abs(float(row.delta_score or 0.0))
            if row.override_score is None or row.ai_score is None or delta < DISAGREEMENT_THRESHOLD:
                continue
            source_session = db.get(DrillSession, row.session_id)
            rep = db.get(User, source_session.rep_id) if source_session else None
            latest_run = db.scalar(
                select(GradingRun)
                .where(GradingRun.session_id == row.session_id)
                .order_by(GradingRun.completed_at.desc(), GradingRun.created_at.desc())
            )
            items.append(
                {
                    "id": f"grading-disagreement-{row.review_id}",
                    "severity": "high" if delta >= 3.5 else "medium",
                    "kind": "grading_disagreement",
                    "title": f"{rep.name if rep else 'Rep'} has a grading disagreement",
                    "description": f"AI score {row.ai_score:.1f} vs override {row.override_score:.1f} ({delta:.1f} point delta).",
                    "occurred_at": _normalize_dt(row.reviewed_at) or refreshed_at,
                    "rep_id": rep.id if rep else None,
                    "scenario_id": source_session.scenario_id if source_session else None,
                    "session_id": row.session_id,
                    "team_id": rep.team_id if rep else None,
                    "baseline_value": row.ai_score,
                    "observed_value": row.override_score,
                    "delta": round(delta, 2),
                    "metadata": {
                        "period_key": period_key,
                        "review_id": row.review_id,
                        "reviewer_id": row.reviewer_id,
                        "rep_name": rep.name if rep else None,
                        "prompt_version_id": latest_run.prompt_version_id if latest_run else None,
                        "scorecard_id": row.scorecard_id,
                    },
                }
            )
        return items

    def refresh_session(self, db: Session, *, session_id: str, refresh_materialized: bool = True) -> dict[str, Any]:
        self.ensure_metric_definitions(db)
        run = self._start_run(db, scope_type="session", scope_id=session_id)
        row_counts: dict[str, Any] = {}
        try:
            session, assignment, rep, manager, scenario = self._session_bundle(db, session_id=session_id)
            team = db.scalar(select(Team).where(Team.id == rep.team_id)) if rep.team_id else None
            scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
            turns = db.scalars(select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())).all()
            events = db.scalars(select(SessionEvent).where(SessionEvent.session_id == session_id).order_by(SessionEvent.event_ts.asc(), SessionEvent.sequence.asc())).all()
            reviews = db.scalars(select(ManagerReview).join(Scorecard, Scorecard.id == ManagerReview.scorecard_id).where(Scorecard.session_id == session_id)).all()
            coaching_notes = db.scalars(select(ManagerCoachingNote).join(Scorecard, Scorecard.id == ManagerCoachingNote.scorecard_id).where(Scorecard.session_id == session_id)).all()

            first_session_at = db.scalar(
                select(func.min(DrillSession.started_at))
                .join(Assignment, Assignment.id == DrillSession.assignment_id)
                .where(Assignment.assigned_by == manager.id, DrillSession.rep_id == rep.id)
            )
            last_session_at = db.scalar(
                select(func.max(DrillSession.started_at))
                .join(Assignment, Assignment.id == DrillSession.assignment_id)
                .where(Assignment.assigned_by == manager.id, DrillSession.rep_id == rep.id)
            )

            self._upsert_manager_dim(db, manager=manager, team=team)
            self._upsert_rep_dim(
                db,
                rep=rep,
                manager_id=manager.id,
                first_session_at=_normalize_dt(first_session_at),
                last_session_at=_normalize_dt(last_session_at),
            )
            if team is not None:
                self._upsert_team_dim(
                    db,
                    team=team,
                    manager=manager,
                    last_session_at=_normalize_dt(last_session_at),
                )
            self._upsert_scenario_dim(db, scenario=scenario)

            fact_session_payload, turn_metrics_payload = self._session_metrics(
                session=session,
                scorecard=scorecard,
                turns=turns,
                events=events,
                reviews=reviews,
                coaching_notes=coaching_notes,
                scenario=scenario,
            )
            fact_session_payload["manager_id"] = manager.id
            fact_session_payload["org_id"] = rep.org_id
            fact_session_payload["team_id"] = rep.team_id
            turn_metrics_payload["manager_id"] = manager.id
            self._ensure_time_dim(db, day_value=fact_session_payload["session_date"])
            self._upsert_session_fact(db, payload=fact_session_payload)
            self._upsert_turn_metrics(db, payload=turn_metrics_payload)

            manager_dim = db.get(AnalyticsDimManager, manager.id)
            if manager_dim is not None:
                manager_dim.last_session_at = max(
                    _normalize_dt(manager_dim.last_session_at) or datetime.min.replace(tzinfo=timezone.utc),
                    _normalize_dt(session.started_at) or _utcnow(),
                )
                manager_dim.rep_count = db.scalar(
                    select(func.count(func.distinct(Assignment.rep_id))).where(Assignment.assigned_by == manager.id)
                ) or 0

            db.flush()
            row_counts["session_fact_rows"] = 1
            row_counts["turn_metric_rows"] = 1
            row_counts.update(self._rebuild_rep_aggregates(db, manager_id=manager.id, rep_id=rep.id, team_id=rep.team_id))
            row_counts.update(self._rebuild_team_aggregates(db, manager_id=manager.id, team_id=rep.team_id))
            row_counts.update(self._rebuild_scenario_aggregates(db, manager_id=manager.id, scenario_id=scenario.id))
            row_counts.update(self._rebuild_coaching_interventions(db, manager_id=manager.id, rep_id=rep.id))
            row_counts.update(self._rebuild_manager_calibration(db, manager_id=manager.id))
            row_counts.update(self._refresh_metric_snapshots(db, manager_id=manager.id, snapshot_date=fact_session_payload["session_date"]))
            row_counts.update(self.ensure_partition_windows(db))
            if refresh_materialized:
                row_counts.update(self._refresh_alert_facts(db, manager_id=manager.id))
                row_counts.update(self._refresh_materialized_views(db, manager_id=manager.id, run_id=run.id))

            self._finish_run(db, run=run, status="completed", row_counts=row_counts)
            return {"status": "completed", "run_id": run.id, **row_counts}
        except Exception as exc:
            self._finish_run(db, run=run, status="failed", row_counts=row_counts, error=str(exc)[:1000])
            raise

    def refresh_manager(self, db: Session, *, manager_id: str) -> dict[str, Any]:
        self.ensure_metric_definitions(db)
        run = self._start_run(db, scope_type="manager", scope_id=manager_id)
        row_counts: dict[str, Any] = {"refreshed_sessions": 0}
        try:
            session_ids = db.scalars(
                select(DrillSession.id)
                .join(Assignment, Assignment.id == DrillSession.assignment_id)
                .where(Assignment.assigned_by == manager_id)
                .order_by(DrillSession.started_at.asc())
            ).all()
            for session_id in session_ids:
                self.refresh_session(db, session_id=session_id, refresh_materialized=False)
                row_counts["refreshed_sessions"] += 1
            row_counts.update(self._refresh_alert_facts(db, manager_id=manager_id))
            row_counts.update(self.ensure_partition_windows(db))
            row_counts.update(self._refresh_materialized_views(db, manager_id=manager_id, run_id=run.id))
            self._finish_run(db, run=run, status="completed", row_counts=row_counts)
            return {"status": "completed", "run_id": run.id, **row_counts}
        except Exception as exc:
            self._finish_run(db, run=run, status="failed", row_counts=row_counts, error=str(exc)[:1000])
            raise

    def backfill_all(self, db: Session) -> dict[str, Any]:
        self.ensure_metric_definitions(db)
        run = self._start_run(db, scope_type="global", scope_id=None)
        row_counts: dict[str, Any] = {"refreshed_managers": 0}
        try:
            row_counts.update(self.ensure_partition_windows(db))
            manager_ids = db.scalars(
                select(func.distinct(Assignment.assigned_by)).where(Assignment.assigned_by.is_not(None))
            ).all()
            for manager_id in manager_ids:
                self.refresh_manager(db, manager_id=manager_id)
                row_counts["refreshed_managers"] += 1
            self._finish_run(db, run=run, status="completed", row_counts=row_counts)
            return {"status": "completed", "run_id": run.id, **row_counts}
        except Exception as exc:
            self._finish_run(db, run=run, status="failed", row_counts=row_counts, error=str(exc)[:1000])
            raise
