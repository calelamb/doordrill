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
from app.models.warehouse import FactRepDaily, FactSession
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

    def _use_warehouse(self, db: Session, *, manager_id: str) -> bool:
        fact_count = db.scalar(select(func.count(FactSession.fact_session_id)).where(FactSession.manager_id == manager_id)) or 0
        return int(fact_count) > 0

    def _warehouse_session_rows(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            select(
                FactSession.session_id.label("session_id"),
                FactSession.manager_id.label("manager_id"),
                FactSession.rep_id.label("rep_id"),
                User.name.label("rep_name"),
                FactSession.scenario_id.label("scenario_id"),
                Scenario.name.label("scenario_name"),
                FactSession.session_date.label("session_date"),
                FactSession.started_at.label("started_at"),
                FactSession.overall_score.label("overall_score"),
                FactSession.score_objection_handling.label("score_objection_handling"),
                FactSession.score_closing_technique.label("score_closing_technique"),
                FactSession.has_manager_review.label("has_manager_review"),
                FactSession.override_score.label("override_score"),
                FactSession.override_delta.label("override_delta"),
                FactSession.has_coaching_note.label("has_coaching_note"),
                FactSession.barge_in_count.label("barge_in_count"),
                FactSession.weakness_tag_1.label("weakness_tag_1"),
                FactSession.weakness_tag_2.label("weakness_tag_2"),
                FactSession.weakness_tag_3.label("weakness_tag_3"),
            )
            .join(User, User.id == FactSession.rep_id)
            .join(Scenario, Scenario.id == FactSession.scenario_id)
            .where(
                FactSession.manager_id == manager_id,
                FactSession.session_date >= date_from.date(),
                FactSession.session_date <= date_to.date(),
            )
            .order_by(FactSession.session_date.asc(), FactSession.started_at.asc(), FactSession.session_id.asc())
        ).mappings().all()
        return [dict(row) for row in rows]

    def _warehouse_rep_daily_rows(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            select(
                FactRepDaily.rep_id.label("rep_id"),
                User.name.label("rep_name"),
                FactRepDaily.session_date.label("session_date"),
                FactRepDaily.session_count.label("session_count"),
                FactRepDaily.scored_count.label("scored_count"),
                FactRepDaily.avg_score.label("avg_score"),
                FactRepDaily.avg_objection_handling.label("avg_objection_handling"),
                FactRepDaily.avg_closing_technique.label("avg_closing_technique"),
                FactRepDaily.total_duration_seconds.label("total_duration_seconds"),
                FactRepDaily.barge_in_count.label("barge_in_count"),
                FactRepDaily.override_count.label("override_count"),
                FactRepDaily.coaching_note_count.label("coaching_note_count"),
            )
            .join(User, User.id == FactRepDaily.rep_id)
            .where(
                FactRepDaily.manager_id == manager_id,
                FactRepDaily.session_date >= date_from.date(),
                FactRepDaily.session_date <= date_to.date(),
            )
            .order_by(User.name.asc(), FactRepDaily.session_date.asc())
        ).mappings().all()
        return [dict(row) for row in rows]

    def _warehouse_score_trend(self, session_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for row in session_rows:
            session_date = row["session_date"]
            if session_date is None:
                continue
            day_key = session_date.isoformat()
            bucket = buckets.setdefault(day_key, {"date": day_key, "session_count": 0, "scored_count": 0, "score_sum": 0.0})
            bucket["session_count"] += 1
            if row["overall_score"] is not None:
                bucket["scored_count"] += 1
                bucket["score_sum"] += float(row["overall_score"])
        return [
            {
                "date": key,
                "session_count": bucket["session_count"],
                "average_score": round(bucket["score_sum"] / bucket["scored_count"], 2) if bucket["scored_count"] else None,
            }
            for key, bucket in sorted(buckets.items())
        ]

    def _warehouse_scenario_pass_rows(self, session_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in session_rows:
            scenario_id = row["scenario_id"]
            if scenario_id is None:
                continue
            group = grouped.setdefault(
                scenario_id,
                {
                    "scenario_id": scenario_id,
                    "scenario_name": row["scenario_name"],
                    "session_count": 0,
                    "scored_session_count": 0,
                    "pass_count": 0,
                    "score_sum": 0.0,
                },
            )
            group["session_count"] += 1
            if row["overall_score"] is not None:
                score = float(row["overall_score"])
                group["scored_session_count"] += 1
                group["score_sum"] += score
                if score >= 7.0:
                    group["pass_count"] += 1

        rows = []
        for group in grouped.values():
            scored = int(group["scored_session_count"])
            rows.append(
                {
                    "scenario_id": group["scenario_id"],
                    "scenario_name": group["scenario_name"],
                    "session_count": int(group["session_count"]),
                    "scored_session_count": scored,
                    "pass_count": int(group["pass_count"]),
                    "average_score": round(group["score_sum"] / scored, 2) if scored else None,
                    "pass_rate": round(group["pass_count"] / scored, 3) if scored else 0.0,
                }
            )
        rows.sort(key=lambda item: (item["pass_rate"], item["average_score"] or 0.0, item["scenario_name"] or ""))
        return rows

    def _warehouse_histogram(self, session_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _score_histogram([float(row["overall_score"]) for row in session_rows if row["overall_score"] is not None])

    def _warehouse_skill_heatmap(self, rep_daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rep_daily_rows:
            rep_id = row["rep_id"]
            group = grouped.setdefault(
                rep_id,
                {
                    "rep_id": rep_id,
                    "rep_name": row["rep_name"],
                    "session_count": 0,
                    "scored_count": 0,
                    "score_weighted_sum": 0.0,
                    "objection_weighted_sum": 0.0,
                    "closing_weighted_sum": 0.0,
                    "duration_seconds": 0,
                    "barge_in_count": 0,
                    "override_count": 0,
                    "coaching_note_count": 0,
                },
            )
            session_count = int(row["session_count"] or 0)
            scored_count = int(row["scored_count"] or 0)
            group["session_count"] += session_count
            group["scored_count"] += scored_count
            if row["avg_score"] is not None:
                group["score_weighted_sum"] += float(row["avg_score"]) * max(scored_count, session_count, 1)
            if row["avg_objection_handling"] is not None:
                group["objection_weighted_sum"] += float(row["avg_objection_handling"]) * max(scored_count, session_count, 1)
            if row["avg_closing_technique"] is not None:
                group["closing_weighted_sum"] += float(row["avg_closing_technique"]) * max(scored_count, session_count, 1)
            group["duration_seconds"] += int(row["total_duration_seconds"] or 0)
            group["barge_in_count"] += int(row["barge_in_count"] or 0)
            group["override_count"] += int(row["override_count"] or 0)
            group["coaching_note_count"] += int(row["coaching_note_count"] or 0)

        items = []
        for group in grouped.values():
            score_weight = max(group["scored_count"], group["session_count"], 1)
            items.append(
                {
                    "rep_id": group["rep_id"],
                    "rep_name": group["rep_name"],
                    "session_count": group["session_count"],
                    "scored_count": group["scored_count"],
                    "average_score": round(group["score_weighted_sum"] / score_weight, 2) if group["score_weighted_sum"] else None,
                    "average_objection_handling": (
                        round(group["objection_weighted_sum"] / score_weight, 2) if group["objection_weighted_sum"] else None
                    ),
                    "average_closing_technique": (
                        round(group["closing_weighted_sum"] / score_weight, 2) if group["closing_weighted_sum"] else None
                    ),
                    "total_duration_seconds": group["duration_seconds"],
                    "barge_in_count": group["barge_in_count"],
                    "override_count": group["override_count"],
                    "coaching_note_count": group["coaching_note_count"],
                }
            )
        items.sort(key=lambda item: (item["average_score"] is None, item["average_score"] or 0.0, item["rep_name"]))
        return items

    def _warehouse_command_center_overrides(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
    ) -> dict[str, Any]:
        session_rows = self._warehouse_session_rows(db, manager_id=manager_id, date_from=date_from, date_to=date_to)
        scores = [float(row["overall_score"]) for row in session_rows if row["overall_score"] is not None]
        weakest_scores: dict[str, list[float]] = {}
        for row in session_rows:
            for key in ("weakness_tag_1", "weakness_tag_2", "weakness_tag_3"):
                tag = row.get(key)
                if not tag or row["overall_score"] is None:
                    continue
                weakest_scores.setdefault(tag, []).append(float(row["overall_score"]))

        weakest_categories = [
            {"category": tag, "average_score": round(sum(values) / len(values), 2), "session_id": None, "focus_turn_id": None}
            for tag, values in weakest_scores.items()
            if values
        ]
        weakest_categories.sort(key=lambda item: item["average_score"])

        return {
            "summary": {
                "team_average_score": round(sum(scores) / len(scores), 2) if scores else None,
                "active_rep_count": len({row["rep_id"] for row in session_rows}),
                "sessions_count": len(session_rows),
                "scored_session_count": len(scores),
            },
            "score_trend": self._warehouse_score_trend(session_rows),
            "score_distribution_histogram": self._warehouse_histogram(session_rows),
            "scenario_pass_matrix": [
                {
                    "scenario_id": row["scenario_id"],
                    "scenario_name": row["scenario_name"],
                    "session_count": row["session_count"],
                    "scored_count": row["scored_session_count"],
                    "pass_count": row["pass_count"],
                    "average_score": row["average_score"],
                    "pass_rate": row["pass_rate"],
                    "sample_session_id": None,
                    "focus_turn_id": None,
                    "latest_session_id": None,
                    "latest_started_at": None,
                }
                for row in self._warehouse_scenario_pass_rows(session_rows)
            ],
            "weakest_categories": weakest_categories[:5],
        }

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
        team_id: str | None = None,
        date_from: datetime,
        date_to: datetime,
        previous_start: datetime,
        previous_end: datetime,
        period: str,
    ) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            payload = self.base.get_command_center(
                db,
                manager_id=manager_id,
                team_id=team_id,
                date_from=date_from,
                date_to=date_to,
                previous_start=previous_start,
                previous_end=previous_end,
                period=period,
            )
            if team_id or not self._use_warehouse(db, manager_id=manager_id):
                return payload

            warehouse = self._warehouse_command_center_overrides(
                db,
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to,
            )
            previous_warehouse = self._warehouse_command_center_overrides(
                db,
                manager_id=manager_id,
                date_from=previous_start,
                date_to=previous_end,
            )
            merged = dict(payload)
            merged_summary = dict(payload.get("summary", {}))
            merged_summary.update(warehouse["summary"])
            previous_score = previous_warehouse["summary"].get("team_average_score")
            current_score = warehouse["summary"].get("team_average_score")
            merged_summary["team_average_delta_vs_previous_period"] = (
                round(current_score - float(previous_score), 2)
                if current_score is not None and previous_score is not None
                else payload.get("summary", {}).get("team_average_delta_vs_previous_period")
            )
            merged["summary"] = merged_summary
            merged["score_trend"] = warehouse["score_trend"]
            merged["score_distribution_histogram"] = warehouse["score_distribution_histogram"]
            merged["scenario_pass_matrix"] = warehouse["scenario_pass_matrix"]
            if warehouse["weakest_categories"]:
                merged["weakest_categories"] = warehouse["weakest_categories"]
            return merged

        return self._with_cache(
            db,
            query_name="command_center",
            manager_id=manager_id,
            cache_params={
                "team_id": team_id,
                "date_from": _cache_dt_iso(date_from),
                "date_to": _cache_dt_iso(date_to),
                "previous_start": _cache_dt_iso(previous_start),
                "previous_end": _cache_dt_iso(previous_end),
                "period": period,
            },
            builder=build,
        )

    def get_scenario_intelligence(
        self,
        db: Session,
        *,
        manager_id: str,
        team_id: str | None = None,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="scenario_intelligence",
            manager_id=manager_id,
            cache_params={"team_id": team_id, "date_from": _cache_dt_iso(date_from), "date_to": _cache_dt_iso(date_to), "period": period},
            builder=lambda: self.base.get_scenario_intelligence(
                db,
                manager_id=manager_id,
                team_id=team_id,
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
        team_id: str | None = None,
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
                "team_id": team_id,
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
                team_id=team_id,
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
        team_id: str | None = None,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="alerts",
            manager_id=manager_id,
            cache_params={"team_id": team_id, "date_from": _cache_dt_iso(date_from), "date_to": _cache_dt_iso(date_to), "period": period},
            builder=lambda: self.base.get_alerts(
                db,
                manager_id=manager_id,
                team_id=team_id,
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
        team_id: str | None = None,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        return self._with_cache(
            db,
            query_name="benchmarks",
            manager_id=manager_id,
            cache_params={"team_id": team_id, "date_from": _cache_dt_iso(date_from), "date_to": _cache_dt_iso(date_to), "period": period},
            builder=lambda: self.base.get_benchmarks(
                db,
                manager_id=manager_id,
                team_id=team_id,
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
        team_id: str | None = None,
        period: str,
        current_start: datetime,
        current_end: datetime,
        previous_start: datetime,
        previous_end: datetime,
    ) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            assignment_scope = (
                select(func.count(Assignment.id))
                .join(User, User.id == Assignment.rep_id)
                .where(User.team_id == team_id)
                if team_id
                else select(func.count(Assignment.id)).where(Assignment.assigned_by == manager_id)
            )
            assignment_count = db.scalar(assignment_scope) or 0
            completed_assignments = (
                db.scalar(
                    (
                        select(func.count(Assignment.id))
                        .join(User, User.id == Assignment.rep_id)
                        .where(
                            User.team_id == team_id,
                            Assignment.status == AssignmentStatus.COMPLETED,
                        )
                        if team_id
                        else select(func.count(Assignment.id)).where(
                            Assignment.assigned_by == manager_id,
                            Assignment.status == AssignmentStatus.COMPLETED,
                        )
                    )
                )
                or 0
            )
            sessions_count = db.scalar(
                select(func.count(AnalyticsFactSession.session_id)).where(
                    AnalyticsFactSession.team_id == team_id if team_id else AnalyticsFactSession.manager_id == manager_id
                )
            ) or 0
            avg_score = db.scalar(
                select(func.avg(AnalyticsFactSession.overall_score)).where(
                    AnalyticsFactSession.team_id == team_id if team_id else AnalyticsFactSession.manager_id == manager_id
                )
            )
            unique_reps = db.scalar(
                (
                    select(func.count(func.distinct(Assignment.rep_id)))
                    .join(User, User.id == Assignment.rep_id)
                    .where(User.team_id == team_id)
                    if team_id
                    else select(func.count(func.distinct(Assignment.rep_id))).where(Assignment.assigned_by == manager_id)
                )
            ) or 0

            completion_stmt = (
                select(
                    Assignment.rep_id.label("rep_id"),
                    User.name.label("rep_name"),
                    func.count(Assignment.id).label("assignment_count"),
                    func.sum(case((Assignment.status == AssignmentStatus.COMPLETED, 1), else_=0)).label("completed_count"),
                )
                .join(User, User.id == Assignment.rep_id)
                .where(
                    Assignment.created_at >= current_start,
                    Assignment.created_at <= current_end,
                )
                .group_by(Assignment.rep_id, User.name)
                .order_by(User.name.asc())
            )
            if team_id:
                completion_stmt = completion_stmt.where(User.team_id == team_id)
            else:
                completion_stmt = completion_stmt.where(Assignment.assigned_by == manager_id)
            completion_rows = db.execute(completion_stmt).mappings().all()

            use_warehouse = False if team_id else self._use_warehouse(db, manager_id=manager_id)
            if use_warehouse:
                warehouse_session_rows = self._warehouse_session_rows(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                )
                warehouse_rep_daily_rows = self._warehouse_rep_daily_rows(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                )
                warehouse_command_center = self._warehouse_command_center_overrides(
                    db,
                    manager_id=manager_id,
                    date_from=current_start,
                    date_to=current_end,
                )
                pass_rate_rows = self._warehouse_scenario_pass_rows(warehouse_session_rows)
                histogram = self._warehouse_histogram(warehouse_session_rows)
                team_skill_heatmap = self._warehouse_skill_heatmap(warehouse_rep_daily_rows)
            else:
                warehouse_command_center = None
                pass_rate_rows = db.execute(
                    select(
                        AnalyticsFactSession.scenario_id.label("scenario_id"),
                        Scenario.name.label("scenario_name"),
                        func.count(AnalyticsFactSession.session_id).label("scored_session_count"),
                        func.sum(case((AnalyticsFactSession.pass_flag.is_(True), 1), else_=0)).label("pass_count"),
                    )
                    .join(Scenario, Scenario.id == AnalyticsFactSession.scenario_id)
                    .where(
                        AnalyticsFactSession.team_id == team_id if team_id else AnalyticsFactSession.manager_id == manager_id,
                        AnalyticsFactSession.overall_score.is_not(None),
                        AnalyticsFactSession.session_date >= current_start.date(),
                        AnalyticsFactSession.session_date <= current_end.date(),
                    )
                    .group_by(AnalyticsFactSession.scenario_id, Scenario.name)
                    .order_by(Scenario.name.asc())
                ).mappings().all()
                histogram_scores = db.scalars(
                    select(AnalyticsFactSession.overall_score).where(
                        AnalyticsFactSession.team_id == team_id if team_id else AnalyticsFactSession.manager_id == manager_id,
                        AnalyticsFactSession.overall_score.is_not(None),
                        AnalyticsFactSession.session_date >= current_start.date(),
                        AnalyticsFactSession.session_date <= current_end.date(),
                    )
                ).all()
                histogram = _score_histogram([float(score) for score in histogram_scores if score is not None])
                team_skill_heatmap = []

            command_center = self.get_command_center(
                db,
                manager_id=manager_id,
                team_id=team_id,
                date_from=current_start,
                date_to=current_end,
                previous_start=previous_start,
                previous_end=previous_end,
                period=period,
            )

            current_avg_score = command_center["summary"]["team_average_score"]
            previous_delta = command_center["summary"]["team_average_delta_vs_previous_period"]
            if use_warehouse and warehouse_command_center is not None:
                sessions_count = warehouse_command_center["summary"]["sessions_count"]
                active_rep_count = warehouse_command_center["summary"]["active_rep_count"]
                average_score = warehouse_command_center["summary"]["team_average_score"]
                score_trend = warehouse_command_center["score_trend"]
            else:
                sessions_count = int(sessions_count)
                active_rep_count = int(unique_reps)
                average_score = round(float(avg_score), 2) if avg_score is not None else None
                score_trend = command_center["score_trend"]
            return {
                "manager_id": manager_id,
                "period": period,
                "date_from": current_start.isoformat(),
                "date_to": current_end.isoformat(),
                "assignment_count": int(assignment_count),
                "completed_assignment_count": int(completed_assignments),
                "sessions_count": int(sessions_count),
                "active_rep_count": int(active_rep_count),
                "average_score": average_score,
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
                "score_distribution_histogram": histogram,
                "summary": command_center["summary"],
                "score_trend": score_trend,
                "scenario_pass_matrix": command_center["scenario_pass_matrix"],
                "rep_risk_matrix": command_center["rep_risk_matrix"],
                "weakest_categories": command_center["weakest_categories"],
                "alerts_preview": command_center["alerts_preview"],
                "team_skill_heatmap": team_skill_heatmap,
            }

        return self._with_cache(
            db,
            query_name="team_analytics",
            manager_id=manager_id,
            cache_params={
                "team_id": team_id,
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
                select(func.count(FactSession.fact_session_id)).where(FactSession.manager_id == manager_id)
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
                    "enabled": self._use_warehouse(db, manager_id=manager_id),
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
