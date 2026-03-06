from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analytics import (
    AnalyticsDimManager,
    AnalyticsFactSession,
    AnalyticsMaterializedView,
    AnalyticsMetricDefinition,
    AnalyticsPartitionWindow,
    AnalyticsRefreshRun,
)
from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus
from app.models.user import User
from app.services.management_analytics_service import ManagementAnalyticsService
from app.services.management_cache_service import ManagementCacheService

logger = logging.getLogger(__name__)


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _cache_dt_iso(value: datetime | None) -> str | None:
    normalized = _normalize_dt(value)
    if normalized is None:
        return None
    return normalized.replace(second=0, microsecond=0).isoformat()


def _score_histogram(scores: list[float]) -> list[dict[str, Any]]:
    bins = [
        {"label": "0-2", "min": 0.0, "max": 2.0, "count": 0},
        {"label": "2-4", "min": 2.0, "max": 4.0, "count": 0},
        {"label": "4-6", "min": 4.0, "max": 6.0, "count": 0},
        {"label": "6-8", "min": 6.0, "max": 8.0, "count": 0},
        {"label": "8-10", "min": 8.0, "max": 10.1, "count": 0},
    ]
    for score in scores:
        for bucket in bins:
            if bucket["min"] <= score < bucket["max"]:
                bucket["count"] += 1
                break
    return bins


class ManagementAnalyticsRuntimeService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base = ManagementAnalyticsService()
        self.cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=self.settings.management_analytics_cache_ttl_seconds,
            max_entries=self.settings.management_analytics_cache_max_entries,
        )

    def _latest_refresh_at(self, db: Session, *, manager_id: str) -> datetime | None:
        manager_dim = db.get(AnalyticsDimManager, manager_id)
        if manager_dim and manager_dim.last_refreshed_at:
            return _normalize_dt(manager_dim.last_refreshed_at)
        return _normalize_dt(
            db.scalar(select(func.max(AnalyticsRefreshRun.completed_at)).where(AnalyticsRefreshRun.status == "completed"))
        )

    def _log_query(self, *, query_name: str, manager_id: str, duration_ms: float, cache_status: str) -> None:
        level = logging.INFO
        if duration_ms >= self.settings.management_analytics_critical_ms:
            level = logging.ERROR
        elif duration_ms >= self.settings.management_analytics_warn_ms:
            level = logging.WARNING
        logger.log(
            level,
            "management_analytics_query",
            extra={
                "query_name": query_name,
                "manager_id": manager_id,
                "duration_ms": round(duration_ms, 2),
                "cache_status": cache_status,
            },
        )

    def _attach_meta(
        self,
        payload: dict[str, Any],
        *,
        query_name: str,
        cache_status: str,
        generated_at: datetime,
        cached_at: datetime | None,
        refresh_at: datetime | None,
        duration_ms: float,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        body = dict(payload)
        body["_meta"] = {
            "query_name": query_name,
            "cache_status": cache_status,
            "generated_at": generated_at.isoformat(),
            "cached_at": cached_at.isoformat() if cached_at else None,
            "analytics_last_refresh_at": refresh_at.isoformat() if refresh_at else None,
            "freshness_seconds": max(0, int((now - refresh_at).total_seconds())) if refresh_at else None,
            "query_duration_ms": round(duration_ms, 2),
            "cache": self.cache.stats(),
        }
        return body

    def _with_cache(
        self,
        db: Session,
        *,
        query_name: str,
        manager_id: str,
        cache_params: dict[str, Any],
        builder: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        refresh_at = self._latest_refresh_at(db, manager_id=manager_id)
        cache_key = self.cache.make_key(
            "manager-analytics",
            {
                "query_name": query_name,
                "manager_id": manager_id,
                "params": cache_params,
                "refresh_at": refresh_at.isoformat() if refresh_at else None,
            },
        )
        cached = self.cache.get_json(cache_key)
        if cached is not None:
            cached_at = _normalize_dt(datetime.fromisoformat(cached["_cached_at"])) if cached.get("_cached_at") else None
            self._log_query(query_name=query_name, manager_id=manager_id, duration_ms=0.0, cache_status="hit")
            return self._attach_meta(
                cached["payload"],
                query_name=query_name,
                cache_status="hit",
                generated_at=cached_at or datetime.now(timezone.utc),
                cached_at=cached_at,
                refresh_at=refresh_at,
                duration_ms=0.0,
            )

        started = time.perf_counter()
        payload = builder()
        duration_ms = (time.perf_counter() - started) * 1000
        generated_at = datetime.now(timezone.utc)
        self.cache.set_json(
            cache_key,
            {
                "_cached_at": generated_at.isoformat(),
                "payload": payload,
            },
        )
        self._log_query(query_name=query_name, manager_id=manager_id, duration_ms=duration_ms, cache_status="miss")
        return self._attach_meta(
            payload,
            query_name=query_name,
            cache_status="miss",
            generated_at=generated_at,
            cached_at=generated_at,
            refresh_at=refresh_at,
            duration_ms=duration_ms,
        )

    def get_command_center(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        previous_start: datetime,
        previous_end: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="command_center",
            manager_id=manager_id,
            cache_params={
                "date_from": _cache_dt_iso(date_from),
                "date_to": _cache_dt_iso(date_to),
                "previous_start": _cache_dt_iso(previous_start),
                "previous_end": _cache_dt_iso(previous_end),
                "period": period,
            },
            builder=lambda: self.base.get_command_center(
                db,
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to,
                previous_start=previous_start,
                previous_end=previous_end,
                period=period,
            ),
        )

    def get_scenario_intelligence(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="scenario_intelligence",
            manager_id=manager_id,
            cache_params={"date_from": _cache_dt_iso(date_from), "date_to": _cache_dt_iso(date_to), "period": period},
            builder=lambda: self.base.get_scenario_intelligence(
                db,
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to,
                period=period,
            ),
        )

    def get_coaching_analytics(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="coaching_analytics",
            manager_id=manager_id,
            cache_params={"date_from": _cache_dt_iso(date_from), "date_to": _cache_dt_iso(date_to), "period": period},
            builder=lambda: self.base.get_coaching_analytics(
                db,
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to,
                period=period,
            ),
        )

    def get_session_explorer(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime | None,
        date_to: datetime | None,
        rep_id: str | None = None,
        scenario_id: str | None = None,
        reviewed: bool | None = None,
        weakness_tag: str | None = None,
        score_min: float | None = None,
        score_max: float | None = None,
        barge_in_only: bool = False,
        search: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="session_explorer",
            manager_id=manager_id,
            cache_params={
                "date_from": _cache_dt_iso(date_from),
                "date_to": _cache_dt_iso(date_to),
                "rep_id": rep_id,
                "scenario_id": scenario_id,
                "reviewed": reviewed,
                "weakness_tag": weakness_tag,
                "score_min": score_min,
                "score_max": score_max,
                "barge_in_only": barge_in_only,
                "search": search,
                "limit": limit,
            },
            builder=lambda: self.base.get_session_explorer(
                db,
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to,
                rep_id=rep_id,
                scenario_id=scenario_id,
                reviewed=reviewed,
                weakness_tag=weakness_tag,
                score_min=score_min,
                score_max=score_max,
                barge_in_only=barge_in_only,
                search=search,
                limit=limit,
            ),
        )

    def get_alerts(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="alerts",
            manager_id=manager_id,
            cache_params={"date_from": _cache_dt_iso(date_from), "date_to": _cache_dt_iso(date_to), "period": period},
            builder=lambda: self.base.get_alerts(
                db,
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to,
                period=period,
            ),
        )

    def get_benchmarks(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="benchmarks",
            manager_id=manager_id,
            cache_params={"date_from": _cache_dt_iso(date_from), "date_to": _cache_dt_iso(date_to), "period": period},
            builder=lambda: self.base.get_benchmarks(
                db,
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to,
                period=period,
            ),
        )

    def get_team_analytics(
        self,
        db: Session,
        *,
        manager_id: str,
        period: str,
        current_start: datetime,
        current_end: datetime,
        previous_start: datetime,
        previous_end: datetime,
    ) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            assignment_count = db.scalar(select(func.count(Assignment.id)).where(Assignment.assigned_by == manager_id)) or 0
            completed_assignments = (
                db.scalar(
                    select(func.count(Assignment.id)).where(
                        Assignment.assigned_by == manager_id,
                        Assignment.status == AssignmentStatus.COMPLETED,
                    )
                )
                or 0
            )
            sessions_count = db.scalar(
                select(func.count(AnalyticsFactSession.session_id)).where(AnalyticsFactSession.manager_id == manager_id)
            ) or 0
            avg_score = db.scalar(
                select(func.avg(AnalyticsFactSession.overall_score)).where(AnalyticsFactSession.manager_id == manager_id)
            )
            unique_reps = db.scalar(select(func.count(func.distinct(Assignment.rep_id))).where(Assignment.assigned_by == manager_id)) or 0

            completion_rows = db.execute(
                select(
                    Assignment.rep_id.label("rep_id"),
                    User.name.label("rep_name"),
                    func.count(Assignment.id).label("assignment_count"),
                    func.sum(case((Assignment.status == AssignmentStatus.COMPLETED, 1), else_=0)).label("completed_count"),
                )
                .join(User, User.id == Assignment.rep_id)
                .where(
                    Assignment.assigned_by == manager_id,
                    Assignment.created_at >= current_start,
                    Assignment.created_at <= current_end,
                )
                .group_by(Assignment.rep_id, User.name)
                .order_by(User.name.asc())
            ).mappings().all()

            pass_rate_rows = db.execute(
                select(
                    AnalyticsFactSession.scenario_id.label("scenario_id"),
                    Scenario.name.label("scenario_name"),
                    func.count(AnalyticsFactSession.session_id).label("scored_session_count"),
                    func.sum(case((AnalyticsFactSession.pass_flag.is_(True), 1), else_=0)).label("pass_count"),
                )
                .join(Scenario, Scenario.id == AnalyticsFactSession.scenario_id)
                .where(
                    AnalyticsFactSession.manager_id == manager_id,
                    AnalyticsFactSession.overall_score.is_not(None),
                    AnalyticsFactSession.session_date >= current_start.date(),
                    AnalyticsFactSession.session_date <= current_end.date(),
                )
                .group_by(AnalyticsFactSession.scenario_id, Scenario.name)
                .order_by(Scenario.name.asc())
            ).mappings().all()

            histogram_scores = db.scalars(
                select(AnalyticsFactSession.overall_score).where(
                    AnalyticsFactSession.manager_id == manager_id,
                    AnalyticsFactSession.overall_score.is_not(None),
                    AnalyticsFactSession.session_date >= current_start.date(),
                    AnalyticsFactSession.session_date <= current_end.date(),
                )
            ).all()

            command_center = self.base.get_command_center(
                db,
                manager_id=manager_id,
                date_from=current_start,
                date_to=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                period=period,
            )

            current_avg_score = command_center["summary"]["team_average_score"]
            previous_delta = command_center["summary"]["team_average_delta_vs_previous_period"]
            return {
                "manager_id": manager_id,
                "period": period,
                "date_from": current_start.isoformat(),
                "date_to": current_end.isoformat(),
                "assignment_count": int(assignment_count),
                "completed_assignment_count": int(completed_assignments),
                "sessions_count": int(sessions_count),
                "active_rep_count": int(unique_reps),
                "average_score": round(float(avg_score), 2) if avg_score is not None else None,
                "completion_rate": round((completed_assignments / assignment_count), 3) if assignment_count else 0.0,
                "team_average_score": current_avg_score,
                "team_average_delta_vs_previous_period": previous_delta,
                "completion_rate_by_rep": [
                    {
                        "rep_id": row["rep_id"],
                        "rep_name": row["rep_name"],
                        "assignment_count": int(row["assignment_count"] or 0),
                        "completed_assignment_count": int(row["completed_count"] or 0),
                        "completion_rate": round(
                            (int(row["completed_count"] or 0) / int(row["assignment_count"] or 1)),
                            3,
                        ) if int(row["assignment_count"] or 0) else 0.0,
                    }
                    for row in completion_rows
                ],
                "scenario_pass_rates": [
                    {
                        "scenario_id": row["scenario_id"],
                        "scenario_name": row["scenario_name"],
                        "scored_session_count": int(row["scored_session_count"] or 0),
                        "pass_count": int(row["pass_count"] or 0),
                        "pass_rate": round(
                            (int(row["pass_count"] or 0) / int(row["scored_session_count"] or 1)),
                            3,
                        ) if int(row["scored_session_count"] or 0) else 0.0,
                    }
                    for row in pass_rate_rows
                ],
                "score_distribution_histogram": _score_histogram([float(score) for score in histogram_scores if score is not None]),
                "summary": command_center["summary"],
                "score_trend": command_center["score_trend"],
                "scenario_pass_matrix": command_center["scenario_pass_matrix"],
                "rep_risk_matrix": command_center["rep_risk_matrix"],
                "weakest_categories": command_center["weakest_categories"],
                "alerts_preview": command_center["alerts_preview"],
            }

        return self._with_cache(
            db,
            query_name="team_analytics",
            manager_id=manager_id,
            cache_params={
                "period": period,
                "current_start": _cache_dt_iso(current_start),
                "current_end": _cache_dt_iso(current_end),
                "previous_start": _cache_dt_iso(previous_start),
                "previous_end": _cache_dt_iso(previous_end),
            },
            builder=build,
        )

    def get_operations_status(self, db: Session, *, manager_id: str) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            last_completed = self._latest_refresh_at(db, manager_id=manager_id)
            recent_runs = db.execute(
                select(AnalyticsRefreshRun)
                .order_by(AnalyticsRefreshRun.started_at.desc())
                .limit(12)
            ).scalars().all()
            failed_runs = db.scalar(
                select(func.count(AnalyticsRefreshRun.id)).where(AnalyticsRefreshRun.status == "failed")
            ) or 0
            running_runs = db.scalar(
                select(func.count(AnalyticsRefreshRun.id)).where(AnalyticsRefreshRun.status == "running")
            ) or 0
            fact_count = db.scalar(
                select(func.count(AnalyticsFactSession.session_id)).where(AnalyticsFactSession.manager_id == manager_id)
            ) or 0
            materialized_rows = db.execute(
                select(AnalyticsMaterializedView)
                .where(AnalyticsMaterializedView.manager_id == manager_id)
                .order_by(AnalyticsMaterializedView.refreshed_at.desc())
            ).scalars().all()
            partition_rows = db.execute(
                select(AnalyticsPartitionWindow)
                .order_by(AnalyticsPartitionWindow.table_name.asc(), AnalyticsPartitionWindow.range_start.asc())
            ).scalars().all()
            manager_dim = db.get(AnalyticsDimManager, manager_id)
            return {
                "manager_id": manager_id,
                "analytics_last_refresh_at": last_completed.isoformat() if last_completed else None,
                "cache": self.cache.stats(),
                "refresh_runs": {
                    "failed_count": int(failed_runs),
                    "running_count": int(running_runs),
                    "recent": [
                        {
                            "id": row.id,
                            "scope_type": row.scope_type,
                            "scope_id": row.scope_id,
                            "status": row.status,
                            "started_at": row.started_at.isoformat() if row.started_at else None,
                            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                            "error": row.error,
                            "row_counts_json": row.row_counts_json,
                        }
                        for row in recent_runs
                    ],
                },
                "warehouse": {
                    "fact_session_count": int(fact_count),
                    "manager_dim_last_refreshed_at": manager_dim.last_refreshed_at.isoformat() if manager_dim and manager_dim.last_refreshed_at else None,
                    "manager_rep_count": int(manager_dim.rep_count or 0) if manager_dim else 0,
                },
                "materialized_views": {
                    "count": len(materialized_rows),
                    "recent": [
                        {
                            "id": row.id,
                            "view_name": row.view_name,
                            "period_key": row.period_key,
                            "row_count": row.row_count,
                            "window_start": row.window_start.isoformat() if row.window_start else None,
                            "window_end": row.window_end.isoformat() if row.window_end else None,
                            "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
                        }
                        for row in materialized_rows[:24]
                    ],
                },
                "partitions": {
                    "count": len(partition_rows),
                    "active": [
                        {
                            "table_name": row.table_name,
                            "partition_key": row.partition_key,
                            "backend": row.backend,
                            "status": row.status,
                            "range_start": row.range_start.isoformat() if row.range_start else None,
                            "range_end": row.range_end.isoformat() if row.range_end else None,
                        }
                        for row in partition_rows
                        if row.status in {"active", "upcoming"}
                    ][:48],
                },
                "runtime": {
                    "redis_configured": bool(self.settings.redis_url),
                    "cache_ttl_seconds": self.settings.management_analytics_cache_ttl_seconds,
                    "warn_ms": self.settings.management_analytics_warn_ms,
                    "critical_ms": self.settings.management_analytics_critical_ms,
                },
            }

        return self._with_cache(
            db,
            query_name="operations_status",
            manager_id=manager_id,
            cache_params={"kind": "operations_status"},
            builder=build,
        )

    def get_metric_definitions(self, db: Session, *, manager_id: str) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            rows = db.scalars(
                select(AnalyticsMetricDefinition)
                .where(AnalyticsMetricDefinition.active.is_(True))
                .order_by(AnalyticsMetricDefinition.entity_type.asc(), AnalyticsMetricDefinition.metric_key.asc())
            ).all()
            return {
                "manager_id": manager_id,
                "items": [
                    {
                        "metric_key": row.metric_key,
                        "display_name": row.display_name,
                        "description": row.description,
                        "entity_type": row.entity_type,
                        "aggregation_method": row.aggregation_method,
                        "owner": row.owner,
                        "metadata_json": row.metadata_json,
                    }
                    for row in rows
                ],
            }

        return self._with_cache(
            db,
            query_name="metric_definitions",
            manager_id=manager_id,
            cache_params={"kind": "metric_definitions"},
            builder=build,
        )
