from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.analytics import (
    AnalyticsFactCoachingIntervention,
    AnalyticsFactManagerCalibration,
    AnalyticsMaterializedView,
    AnalyticsFactSession,
)
from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.session import SessionTurn
from app.models.types import AssignmentStatus
from app.models.user import User

RUBRIC_CATEGORY_KEYS = {
    "opening": "opening",
    "pitch": "pitch",
    "pitch_delivery": "pitch",
    "objection_handling": "objection_handling",
    "closing": "closing",
    "closing_technique": "closing",
    "professionalism": "professionalism",
}


@dataclass
class SessionRecord:
    session_id: str
    rep_id: str
    rep_name: str
    scenario_id: str
    scenario_name: str
    scenario_difficulty: int
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    overall_score: float | None
    category_scores: dict[str, Any]
    weakness_tags: list[str]
    highlights: list[dict[str, Any]]
    manager_reviewed: bool
    latest_reviewed_at: datetime | None
    latest_coaching_note_preview: str | None
    assignment_status: str
    session_status: str
    focus_turn_id: str | None
    evidence_turn_ids: list[str]


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _score_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("score")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


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


def _severity_rank(level: str) -> int:
    if level == "high":
        return 3
    if level == "medium":
        return 2
    return 1


def _enum_value(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    raw = getattr(value, "value", value)
    return str(raw)


def _category_scores_from_fact(row: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if row.opening_score is not None:
        payload["opening"] = {"score": float(row.opening_score)}
    if row.pitch_score is not None:
        payload["pitch"] = {"score": float(row.pitch_score)}
        payload["pitch_delivery"] = {"score": float(row.pitch_score)}
    if row.objection_score is not None:
        payload["objection_handling"] = {"score": float(row.objection_score)}
    if row.closing_score is not None:
        payload["closing"] = {"score": float(row.closing_score)}
        payload["closing_technique"] = {"score": float(row.closing_score)}
    if row.professionalism_score is not None:
        payload["professionalism"] = {"score": float(row.professionalism_score)}
    return payload


def _focus_turn_id(highlights: list[dict[str, Any]] | None, evidence_turn_ids: list[str] | None) -> str | None:
    for turn_id in evidence_turn_ids or []:
        if turn_id:
            return turn_id
    for item in highlights or []:
        turn_id = item.get("turn_id")
        if turn_id:
            return turn_id
    return None


class ManagementAnalyticsService:
    def __init__(self, *, prefer_materialized_views: bool = True) -> None:
        self.prefer_materialized_views = prefer_materialized_views

    def _get_materialized_payload(self, db: Session, *, manager_id: str, view_name: str, period: str) -> dict[str, Any] | None:
        if not self.prefer_materialized_views or period not in {"7", "30", "90"}:
            return None
        row = db.scalar(
            select(AnalyticsMaterializedView)
            .where(
                AnalyticsMaterializedView.manager_id == manager_id,
                AnalyticsMaterializedView.view_name == view_name,
                AnalyticsMaterializedView.period_key == period,
            )
            .order_by(AnalyticsMaterializedView.refreshed_at.desc())
            .limit(1)
        )
        if row is None:
            return None
        payload = dict(row.payload_json or {})
        payload.setdefault("_projection", {})
        payload["_projection"] = {
            "view_name": view_name,
            "period_key": period,
            "window_start": row.window_start.isoformat() if row.window_start else None,
            "window_end": row.window_end.isoformat() if row.window_end else None,
            "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
            "row_count": row.row_count,
        }
        return payload

    def _load_sessions(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[SessionRecord]:
        latest_coaching_note = (
            select(ManagerCoachingNote.note)
            .where(ManagerCoachingNote.scorecard_id == Scorecard.id)
            .order_by(ManagerCoachingNote.created_at.desc())
            .limit(1)
            .correlate(Scorecard)
            .scalar_subquery()
        )

        stmt = (
            select(
                AnalyticsFactSession.session_id.label("session_id"),
                AnalyticsFactSession.rep_id.label("rep_id"),
                User.name.label("rep_name"),
                AnalyticsFactSession.scenario_id.label("scenario_id"),
                Scenario.name.label("scenario_name"),
                AnalyticsFactSession.difficulty.label("scenario_difficulty"),
                AnalyticsFactSession.started_at.label("started_at"),
                AnalyticsFactSession.ended_at.label("ended_at"),
                AnalyticsFactSession.duration_seconds.label("duration_seconds"),
                AnalyticsFactSession.overall_score.label("overall_score"),
                AnalyticsFactSession.opening_score.label("opening_score"),
                AnalyticsFactSession.pitch_score.label("pitch_score"),
                AnalyticsFactSession.objection_score.label("objection_score"),
                AnalyticsFactSession.closing_score.label("closing_score"),
                AnalyticsFactSession.professionalism_score.label("professionalism_score"),
                AnalyticsFactSession.weakness_tags_json.label("weakness_tags"),
                Scorecard.highlights.label("highlights"),
                Scorecard.evidence_turn_ids.label("evidence_turn_ids"),
                AnalyticsFactSession.manager_reviewed.label("manager_reviewed"),
                AnalyticsFactSession.latest_reviewed_at.label("latest_reviewed_at"),
                latest_coaching_note.label("latest_coaching_note_preview"),
                Assignment.status.label("assignment_status"),
                AnalyticsFactSession.status.label("session_status"),
            )
            .join(Assignment, Assignment.id == AnalyticsFactSession.assignment_id)
            .join(User, User.id == AnalyticsFactSession.rep_id)
            .join(Scenario, Scenario.id == AnalyticsFactSession.scenario_id)
            .outerjoin(Scorecard, Scorecard.session_id == AnalyticsFactSession.session_id)
            .where(AnalyticsFactSession.manager_id == manager_id)
            .order_by(AnalyticsFactSession.started_at.desc())
        )
        if date_from is not None:
            stmt = stmt.where(AnalyticsFactSession.session_date >= date_from.date())
        if date_to is not None:
            stmt = stmt.where(AnalyticsFactSession.session_date <= date_to.date())

        rows = db.execute(stmt).mappings().all()
        return [
            SessionRecord(
                session_id=row["session_id"],
                rep_id=row["rep_id"],
                rep_name=row["rep_name"],
                scenario_id=row["scenario_id"],
                scenario_name=row["scenario_name"],
                scenario_difficulty=int(row["scenario_difficulty"] or 0),
                started_at=_normalize_dt(row["started_at"]),
                ended_at=_normalize_dt(row["ended_at"]),
                duration_seconds=row["duration_seconds"],
                overall_score=float(row["overall_score"]) if row["overall_score"] is not None else None,
                category_scores=_category_scores_from_fact(row),
                weakness_tags=row["weakness_tags"] or [],
                highlights=row["highlights"] or [],
                manager_reviewed=bool(row["manager_reviewed"]),
                latest_reviewed_at=_normalize_dt(row["latest_reviewed_at"]),
                latest_coaching_note_preview=row["latest_coaching_note_preview"],
                assignment_status=_enum_value(row["assignment_status"]),
                session_status=_enum_value(row["session_status"]),
                focus_turn_id=_focus_turn_id(row["highlights"] or [], row["evidence_turn_ids"] or []),
                evidence_turn_ids=list(row["evidence_turn_ids"] or []),
            )
            for row in rows
        ]

    def _load_objection_tags(self, db: Session, session_ids: list[str]) -> dict[str, list[str]]:
        if not session_ids:
            return {}
        rows = db.execute(
            select(AnalyticsFactSession.session_id, AnalyticsFactSession.objection_tags_json).where(
                AnalyticsFactSession.session_id.in_(session_ids)
            )
        ).all()
        return {session_id: list(tags or []) for session_id, tags in rows}

    def _load_transcript_previews(self, db: Session, session_ids: list[str]) -> dict[str, str]:
        if not session_ids:
            return {}
        rows = db.execute(
            select(SessionTurn.session_id, SessionTurn.turn_index, SessionTurn.text)
            .where(SessionTurn.session_id.in_(session_ids))
            .order_by(SessionTurn.session_id.asc(), SessionTurn.turn_index.asc())
        ).all()
        previews: dict[str, str] = {}
        for session_id, _, text in rows:
            if session_id not in previews and text:
                previews[session_id] = text[:220]
        return previews

    def _load_barge_in_counts(self, db: Session, session_ids: list[str]) -> dict[str, int]:
        if not session_ids:
            return {}
        rows = db.execute(
            select(AnalyticsFactSession.session_id, AnalyticsFactSession.barge_in_count).where(
                AnalyticsFactSession.session_id.in_(session_ids)
            )
        ).all()
        return {session_id: int(count or 0) for session_id, count in rows}

    def _load_assignment_completion(self, db: Session, *, manager_id: str, date_from: datetime, date_to: datetime) -> dict[str, dict[str, Any]]:
        rows = db.execute(
            select(
                Assignment.rep_id.label("rep_id"),
                User.name.label("rep_name"),
                func.count(Assignment.id).label("assignment_count"),
                func.sum(case((Assignment.status == AssignmentStatus.COMPLETED, 1), else_=0)).label("completed_count"),
            )
            .join(User, User.id == Assignment.rep_id)
            .where(
                Assignment.assigned_by == manager_id,
                Assignment.created_at >= date_from,
                Assignment.created_at <= date_to,
            )
            .group_by(Assignment.rep_id, User.name)
        ).mappings().all()
        return {
            row["rep_id"]: {
                "rep_name": row["rep_name"],
                "assignment_count": int(row["assignment_count"] or 0),
                "completed_count": int(row["completed_count"] or 0),
                "completion_rate": round(
                    (int(row["completed_count"] or 0) / int(row["assignment_count"] or 1)),
                    3,
                )
                if int(row["assignment_count"] or 0)
                else 0.0,
            }
            for row in rows
        }

    def _rep_risk_matrix(
        self,
        sessions: list[SessionRecord],
        completion_rows: dict[str, dict[str, Any]],
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        sessions_by_rep: dict[str, list[SessionRecord]] = defaultdict(list)
        for session in sessions:
            if session.overall_score is not None:
                sessions_by_rep[session.rep_id].append(session)

        rows: list[dict[str, Any]] = []
        for rep_id, rep_sessions in sessions_by_rep.items():
            rep_sessions.sort(key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc))
            scores = [item.overall_score for item in rep_sessions if item.overall_score is not None]
            if not scores:
                continue
            focus_session = min(
                rep_sessions,
                key=lambda item: (
                    item.overall_score if item.overall_score is not None else 11,
                    -((item.started_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp()),
                ),
            )
            avg_score = round(sum(scores) / len(scores), 2)
            delta = round(scores[-1] - scores[0], 2) if len(scores) >= 2 else 0.0
            volatility = round(pstdev(scores), 2) if len(scores) >= 2 else 0.0
            red_flags = sum(1 for score in scores if score < 6.0)
            review_gap = sum(1 for item in rep_sessions if item.overall_score is not None and not item.manager_reviewed)
            completion = completion_rows.get(rep_id, {})
            completion_rate = float(completion.get("completion_rate", 0.0))

            risk_score = 0.0
            if avg_score < 6.0:
                risk_score += 2.0
            elif avg_score < 7.0:
                risk_score += 1.0
            if delta < -0.5:
                risk_score += 1.5
            elif delta < 0:
                risk_score += 0.75
            if volatility >= 1.5:
                risk_score += 1.0
            if completion_rate < 0.65:
                risk_score += 1.0
            if red_flags >= 2:
                risk_score += 1.0
            if review_gap >= 2:
                risk_score += 0.5

            if risk_score >= 4:
                level = "high"
            elif risk_score >= 2:
                level = "medium"
            else:
                level = "low"

            rows.append(
                {
                    "rep_id": rep_id,
                    "rep_name": rep_sessions[0].rep_name,
                    "average_score": avg_score,
                    "score_delta": delta,
                    "volatility": volatility,
                    "completion_rate": completion_rate,
                    "red_flag_count": red_flags,
                    "unreviewed_scored_sessions": review_gap,
                    "risk_level": level,
                    "risk_score": round(risk_score, 2),
                    "session_id": focus_session.session_id,
                    "focus_turn_id": focus_session.focus_turn_id,
                }
            )

        rows.sort(key=lambda item: (item["risk_score"], -item["average_score"]), reverse=True)
        return rows[:limit]

    def _rep_regression_anomalies(self, sessions: list[SessionRecord]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        grouped: dict[str, list[SessionRecord]] = defaultdict(list)
        for session in sessions:
            if session.overall_score is not None:
                grouped[session.rep_id].append(session)

        for rep_sessions in grouped.values():
            rep_sessions.sort(key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc))
            if len(rep_sessions) < 5:
                continue
            baseline_sessions = rep_sessions[:-3]
            recent_sessions = rep_sessions[-3:]
            baseline_scores = [item.overall_score for item in baseline_sessions if item.overall_score is not None]
            recent_scores = [item.overall_score for item in recent_sessions if item.overall_score is not None]
            if len(baseline_scores) < 2 or not recent_scores:
                continue

            baseline_avg = sum(baseline_scores) / len(baseline_scores)
            recent_avg = sum(recent_scores) / len(recent_scores)
            baseline_std = pstdev(baseline_scores) if len(baseline_scores) >= 2 else 0.0
            delta = round(recent_avg - baseline_avg, 2)
            z_score = round(delta / baseline_std, 2) if baseline_std > 0 else (-2.0 if delta <= -1.0 else 0.0)
            if delta > -0.8 or z_score > -1.0:
                continue

            severity = "high" if z_score <= -1.75 or delta <= -1.4 else "medium"
            focus_session = recent_sessions[-1]
            rows.append(
                {
                    "id": f"rep-stat-regression-{focus_session.rep_id}",
                    "severity": severity,
                    "kind": "rep_statistical_regression",
                    "title": f"{focus_session.rep_name} is falling below baseline",
                    "description": f"Recent avg {recent_avg:.1f} vs baseline {baseline_avg:.1f} ({delta:+.1f}, z={z_score:+.1f}).",
                    "occurred_at": focus_session.started_at.isoformat() if focus_session.started_at else datetime.now(timezone.utc).isoformat(),
                    "rep_id": focus_session.rep_id,
                    "rep_name": focus_session.rep_name,
                    "session_id": focus_session.session_id,
                    "scenario_id": focus_session.scenario_id,
                    "focus_turn_id": focus_session.focus_turn_id,
                    "baseline_value": round(baseline_avg, 2),
                    "observed_value": round(recent_avg, 2),
                    "delta": delta,
                    "z_score": z_score,
                }
            )
        return rows

    def _scenario_regression_anomalies(self, sessions: list[SessionRecord]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        grouped: dict[str, list[SessionRecord]] = defaultdict(list)
        for session in sessions:
            if session.overall_score is not None:
                grouped[session.scenario_id].append(session)

        for scenario_sessions in grouped.values():
            scenario_sessions.sort(key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc))
            if len(scenario_sessions) < 6:
                continue
            split = max(3, len(scenario_sessions) // 2)
            baseline_sessions = scenario_sessions[:-split]
            recent_sessions = scenario_sessions[-split:]
            if len(baseline_sessions) < 3 or len(recent_sessions) < 3:
                continue
            baseline_pass = sum(1 for item in baseline_sessions if (item.overall_score or 0) >= 7.0) / len(baseline_sessions)
            recent_pass = sum(1 for item in recent_sessions if (item.overall_score or 0) >= 7.0) / len(recent_sessions)
            baseline_avg = sum(item.overall_score or 0 for item in baseline_sessions) / len(baseline_sessions)
            recent_avg = sum(item.overall_score or 0 for item in recent_sessions) / len(recent_sessions)
            if recent_pass >= baseline_pass - 0.2 and recent_avg >= baseline_avg - 0.8:
                continue

            focus_session = recent_sessions[-1]
            rows.append(
                {
                    "id": f"scenario-pass-regression-{focus_session.scenario_id}",
                    "severity": "medium",
                    "kind": "scenario_statistical_regression",
                    "title": f"{focus_session.scenario_name} is regressing",
                    "description": f"Recent pass {recent_pass * 100:.0f}% vs baseline {baseline_pass * 100:.0f}%; recent avg {recent_avg:.1f}.",
                    "occurred_at": focus_session.started_at.isoformat() if focus_session.started_at else datetime.now(timezone.utc).isoformat(),
                    "rep_id": focus_session.rep_id,
                    "rep_name": focus_session.rep_name,
                    "session_id": focus_session.session_id,
                    "scenario_id": focus_session.scenario_id,
                    "focus_turn_id": focus_session.focus_turn_id,
                    "baseline_value": round(baseline_pass, 3),
                    "observed_value": round(recent_pass, 3),
                    "delta": round(recent_pass - baseline_pass, 3),
                }
            )
        return rows

    def _build_alerts(
        self,
        sessions: list[SessionRecord],
        rep_risk_matrix: list[dict[str, Any]],
        scenario_rows: list[dict[str, Any]],
        *,
        overdue_assignments: int = 0,
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for session in sessions:
            if session.overall_score is not None and session.overall_score < 6.0 and not session.manager_reviewed:
                alerts.append(
                    {
                        "id": f"session-red-flag-{session.session_id}",
                        "severity": "high",
                        "kind": "session_red_flag",
                        "title": f"{session.rep_name} needs review",
                        "description": f"{session.scenario_name} scored {session.overall_score:.1f} and is still unreviewed.",
                        "occurred_at": session.started_at.isoformat() if session.started_at else now.isoformat(),
                        "rep_id": session.rep_id,
                        "rep_name": session.rep_name,
                        "session_id": session.session_id,
                        "scenario_id": session.scenario_id,
                        "focus_turn_id": session.focus_turn_id,
                    }
                )

        for rep in rep_risk_matrix:
            if rep["risk_level"] != "high":
                continue
            alerts.append(
                {
                    "id": f"rep-risk-{rep['rep_id']}",
                    "severity": "high",
                    "kind": "rep_regression_risk",
                    "title": f"{rep['rep_name']} is trending down",
                    "description": f"Average {rep['average_score']:.1f}, delta {rep['score_delta']:+.1f}, volatility {rep['volatility']:.1f}.",
                    "occurred_at": now.isoformat(),
                    "rep_id": rep["rep_id"],
                    "rep_name": rep["rep_name"],
                    "session_id": rep.get("session_id"),
                    "scenario_id": None,
                    "focus_turn_id": rep.get("focus_turn_id"),
                }
            )

        for scenario in scenario_rows:
            if scenario["session_count"] >= 3 and scenario["pass_rate"] < 0.6:
                alerts.append(
                    {
                        "id": f"scenario-fail-spike-{scenario['scenario_id']}",
                        "severity": "medium",
                        "kind": "scenario_fail_rate",
                        "title": f"{scenario['scenario_name']} is underperforming",
                        "description": f"Pass rate is {scenario['pass_rate'] * 100:.0f}% across {scenario['session_count']} sessions.",
                        "occurred_at": now.isoformat(),
                        "rep_id": None,
                        "rep_name": None,
                        "session_id": scenario.get("sample_session_id"),
                        "scenario_id": scenario["scenario_id"],
                        "focus_turn_id": scenario.get("focus_turn_id"),
                    }
                )

        if overdue_assignments:
            alerts.append(
                {
                    "id": "overdue-assignments",
                    "severity": "medium",
                    "kind": "overdue_assignments",
                    "title": "Assignments are overdue",
                    "description": f"{overdue_assignments} assignments are overdue and need follow-up.",
                    "occurred_at": now.isoformat(),
                    "rep_id": None,
                    "rep_name": None,
                    "session_id": None,
                    "scenario_id": None,
                }
            )

        alerts.extend(self._rep_regression_anomalies(sessions))
        alerts.extend(self._scenario_regression_anomalies(sessions))
        alerts.sort(key=lambda item: (_severity_rank(item["severity"]), item["occurred_at"]), reverse=True)
        return alerts[:24]

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
        materialized = self._get_materialized_payload(db, manager_id=manager_id, view_name="command_center", period=period)
        if materialized is not None:
            return materialized
        sessions = self._load_sessions(db, manager_id=manager_id, date_from=date_from, date_to=date_to)
        previous_sessions = self._load_sessions(db, manager_id=manager_id, date_from=previous_start, date_to=previous_end)
        session_ids = [session.session_id for session in sessions]
        completion_rows = self._load_assignment_completion(db, manager_id=manager_id, date_from=date_from, date_to=date_to)

        scores = [session.overall_score for session in sessions if session.overall_score is not None]
        previous_scores = [session.overall_score for session in previous_sessions if session.overall_score is not None]
        avg_score = round(sum(scores) / len(scores), 2) if scores else None
        previous_avg = round(sum(previous_scores) / len(previous_scores), 2) if previous_scores else None

        category_values: dict[str, list[float]] = defaultdict(list)
        category_focus: dict[str, dict[str, Any]] = {}
        trend_buckets: dict[str, dict[str, Any]] = {}
        scenario_groups: dict[str, dict[str, Any]] = {}
        for session in sessions:
            if session.started_at:
                day_key = session.started_at.date().isoformat()
                bucket = trend_buckets.setdefault(day_key, {"date": day_key, "session_count": 0, "scored_count": 0, "score_sum": 0.0})
                bucket["session_count"] += 1
                if session.overall_score is not None:
                    bucket["scored_count"] += 1
                    bucket["score_sum"] += session.overall_score

            if session.overall_score is not None:
                group = scenario_groups.setdefault(
                    session.scenario_id,
                    {
                        "scenario_id": session.scenario_id,
                        "scenario_name": session.scenario_name,
                        "difficulty": session.scenario_difficulty,
                        "session_count": 0,
                        "scored_count": 0,
                        "pass_count": 0,
                        "score_sum": 0.0,
                        "sample_session_id": session.session_id,
                        "focus_turn_id": session.focus_turn_id,
                        "lowest_score": session.overall_score if session.overall_score is not None else 11.0,
                    },
                )
                group["session_count"] += 1
                group["scored_count"] += 1
                group["score_sum"] += session.overall_score
                if session.overall_score >= 7.0:
                    group["pass_count"] += 1
                if session.overall_score is not None and session.overall_score <= group["lowest_score"]:
                    group["lowest_score"] = session.overall_score
                    group["sample_session_id"] = session.session_id
                    group["focus_turn_id"] = session.focus_turn_id

            for raw_key, normalized_key in RUBRIC_CATEGORY_KEYS.items():
                value = _score_value(session.category_scores.get(raw_key))
                if value is not None:
                    category_values[normalized_key].append(value)
                    current = category_focus.get(normalized_key)
                    if current is None or value <= current["score"]:
                        category_focus[normalized_key] = {
                            "score": value,
                            "session_id": session.session_id,
                            "focus_turn_id": session.focus_turn_id,
                        }

        weakest_categories = [
            {
                "category": key,
                "average_score": round(sum(values) / len(values), 2),
                "session_id": category_focus.get(key, {}).get("session_id"),
                "focus_turn_id": category_focus.get(key, {}).get("focus_turn_id"),
            }
            for key, values in category_values.items()
            if values
        ]
        weakest_categories.sort(key=lambda item: item["average_score"])

        scenario_rows = [
            {
                **group,
                "average_score": round(group["score_sum"] / group["scored_count"], 2) if group["scored_count"] else None,
                "pass_rate": round(group["pass_count"] / group["scored_count"], 3) if group["scored_count"] else 0.0,
                "sample_session_id": group["sample_session_id"],
                "focus_turn_id": group["focus_turn_id"],
            }
            for group in scenario_groups.values()
        ]
        scenario_rows.sort(key=lambda item: (item["pass_rate"], item["average_score"] or 0))

        rep_risk_matrix = self._rep_risk_matrix(sessions, completion_rows)
        overdue_assignments = (
            db.scalar(
                select(func.count(Assignment.id)).where(
                    Assignment.assigned_by == manager_id,
                    Assignment.status != AssignmentStatus.COMPLETED,
                    Assignment.due_at.is_not(None),
                    Assignment.due_at < datetime.now(timezone.utc),
                )
            )
            or 0
        )
        alerts = self._build_alerts(sessions, rep_risk_matrix, scenario_rows, overdue_assignments=int(overdue_assignments))

        trend = []
        for key in sorted(trend_buckets):
            bucket = trend_buckets[key]
            trend.append(
                {
                    "date": key,
                    "session_count": bucket["session_count"],
                    "average_score": round(bucket["score_sum"] / bucket["scored_count"], 2) if bucket["scored_count"] else None,
                }
            )

        review_coverage = round(
            len([session for session in sessions if session.overall_score is not None and session.manager_reviewed]) / len(scores),
            3,
        ) if scores else 0.0

        return {
            "manager_id": manager_id,
            "period": period,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "summary": {
                "team_average_score": avg_score,
                "team_average_delta_vs_previous_period": (
                    round(avg_score - previous_avg, 2)
                    if avg_score is not None and previous_avg is not None
                    else None
                ),
                "completion_rate": round(
                    (
                        sum(item["completed_count"] for item in completion_rows.values())
                        / max(1, sum(item["assignment_count"] for item in completion_rows.values()))
                    ),
                    3,
                ) if completion_rows else 0.0,
                "review_coverage_rate": review_coverage,
                "active_rep_count": len({session.rep_id for session in sessions}),
                "reps_at_risk": len([row for row in rep_risk_matrix if row["risk_level"] != "low"]),
                "overdue_assignments": int(overdue_assignments),
                "sessions_count": len(sessions),
                "scored_session_count": len(scores),
            },
            "score_trend": trend,
            "score_distribution_histogram": _score_histogram([float(score) for score in scores]),
            "scenario_pass_matrix": scenario_rows,
            "rep_risk_matrix": rep_risk_matrix,
            "weakest_categories": weakest_categories[:5],
            "alerts_preview": alerts[:6],
        }

    def get_scenario_intelligence(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        materialized = self._get_materialized_payload(db, manager_id=manager_id, view_name="scenario_intelligence", period=period)
        if materialized is not None:
            return materialized
        sessions = self._load_sessions(db, manager_id=manager_id, date_from=date_from, date_to=date_to)
        session_ids = [session.session_id for session in sessions]
        objection_tags = self._load_objection_tags(db, session_ids)

        grouped: dict[str, dict[str, Any]] = {}
        for session in sessions:
            group = grouped.setdefault(
                session.scenario_id,
                {
                    "scenario_id": session.scenario_id,
                    "scenario_name": session.scenario_name,
                    "difficulty": session.scenario_difficulty,
                    "session_count": 0,
                    "scored_count": 0,
                    "pass_count": 0,
                    "score_sum": 0.0,
                    "duration_samples": [],
                    "rep_scores": defaultdict(list),
                    "weakness_tags": Counter(),
                    "objections": Counter(),
                },
            )
            group["session_count"] += 1
            if session.duration_seconds:
                group["duration_samples"].append(session.duration_seconds)
            if session.overall_score is not None:
                group["scored_count"] += 1
                group["score_sum"] += session.overall_score
                group["rep_scores"][session.rep_id].append(session.overall_score)
                if session.overall_score >= 7.0:
                    group["pass_count"] += 1
                lowest_score = group.get("lowest_score")
                if lowest_score is None or session.overall_score <= lowest_score:
                    group["lowest_score"] = session.overall_score
                    group["sample_session_id"] = session.session_id
                    group["focus_turn_id"] = session.focus_turn_id
            for tag in session.weakness_tags:
                group["weakness_tags"][tag] += 1
            for tag in objection_tags.get(session.session_id, []):
                group["objections"][tag] += 1

        items = []
        difficulty_bands: dict[int, dict[str, Any]] = defaultdict(lambda: {"difficulty": 0, "session_count": 0, "scored_count": 0, "pass_count": 0, "score_sum": 0.0})
        objection_failure_map = []
        for group in grouped.values():
            improvement_samples = []
            for scores in group["rep_scores"].values():
                if len(scores) >= 2:
                    improvement_samples.append(scores[-1] - scores[0])

            average_score = round(group["score_sum"] / group["scored_count"], 2) if group["scored_count"] else None
            pass_rate = round(group["pass_count"] / group["scored_count"], 3) if group["scored_count"] else 0.0
            item = {
                "scenario_id": group["scenario_id"],
                "scenario_name": group["scenario_name"],
                "difficulty": group["difficulty"],
                "session_count": group["session_count"],
                "scored_session_count": group["scored_count"],
                "pass_rate": pass_rate,
                "average_score": average_score,
                "rep_count": len(group["rep_scores"]),
                "average_duration_seconds": round(sum(group["duration_samples"]) / len(group["duration_samples"])) if group["duration_samples"] else None,
                "improvement_delta": round(sum(improvement_samples) / len(improvement_samples), 2) if improvement_samples else None,
                "top_weakness_tags": [tag for tag, _ in group["weakness_tags"].most_common(4)],
                "top_objection_tags": [tag for tag, _ in group["objections"].most_common(4)],
                "sample_session_id": group.get("sample_session_id"),
                "focus_turn_id": group.get("focus_turn_id"),
            }
            items.append(item)

            band = difficulty_bands[group["difficulty"]]
            band["difficulty"] = group["difficulty"]
            band["session_count"] += group["session_count"]
            band["scored_count"] += group["scored_count"]
            band["pass_count"] += group["pass_count"]
            band["score_sum"] += group["score_sum"]

            for tag, count in group["objections"].most_common(3):
                objection_failure_map.append(
                    {
                        "scenario_id": group["scenario_id"],
                        "scenario_name": group["scenario_name"],
                        "objection_tag": tag,
                        "count": count,
                    }
                )

        items.sort(key=lambda item: (item["pass_rate"], item["average_score"] or 0))
        bands = [
            {
                "difficulty": band["difficulty"],
                "session_count": band["session_count"],
                "average_score": round(band["score_sum"] / band["scored_count"], 2) if band["scored_count"] else None,
                "pass_rate": round(band["pass_count"] / band["scored_count"], 3) if band["scored_count"] else 0.0,
            }
            for band in sorted(difficulty_bands.values(), key=lambda value: value["difficulty"])
        ]

        return {
            "manager_id": manager_id,
            "period": period,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "items": items,
            "difficulty_bands": bands,
            "objection_failure_map": objection_failure_map[:24],
        }

    def get_coaching_analytics(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        sessions = self._load_sessions(db, manager_id=manager_id, date_from=date_from, date_to=date_to)
        session_ids = [session.session_id for session in sessions]
        if not session_ids:
            return {
                "manager_id": manager_id,
                "period": period,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "summary": {
                    "coaching_note_count": 0,
                    "review_count": 0,
                    "override_rate": 0.0,
                    "average_override_delta": None,
                },
                "coaching_uplift": [],
                "weakness_tag_uplift": [],
                "manager_calibration": [],
                "intervention_timeline": [],
                "recent_notes": [],
            }

        session_map = {session.session_id: session for session in sessions}
        notes = db.scalars(
            select(ManagerCoachingNote)
            .where(
                ManagerCoachingNote.scorecard_id.in_(
                    select(Scorecard.id).where(Scorecard.session_id.in_(session_ids))
                ),
                ManagerCoachingNote.created_at >= date_from,
                ManagerCoachingNote.created_at <= date_to,
            )
            .order_by(ManagerCoachingNote.created_at.desc())
        ).all()
        note_map = {note.id: note for note in notes}

        coaching_facts = db.scalars(
            select(AnalyticsFactCoachingIntervention)
            .where(
                AnalyticsFactCoachingIntervention.manager_id == manager_id,
                AnalyticsFactCoachingIntervention.session_id.in_(session_ids),
                AnalyticsFactCoachingIntervention.note_created_at >= date_from,
                AnalyticsFactCoachingIntervention.note_created_at <= date_to,
            )
            .order_by(AnalyticsFactCoachingIntervention.note_created_at.desc())
        ).all()
        calibration_facts = db.scalars(
            select(AnalyticsFactManagerCalibration)
            .where(
                AnalyticsFactManagerCalibration.manager_id == manager_id,
                AnalyticsFactManagerCalibration.session_id.in_(session_ids),
                AnalyticsFactManagerCalibration.reviewed_at >= date_from,
                AnalyticsFactManagerCalibration.reviewed_at <= date_to,
            )
            .order_by(AnalyticsFactManagerCalibration.reviewed_at.desc())
        ).all()

        uplift_rows = []
        tag_rollups: dict[str, dict[str, Any]] = defaultdict(lambda: {"deltas": [], "improved_count": 0, "regressed_count": 0, "flat_count": 0})
        recent_notes = []
        intervention_segments: dict[tuple[str, str], int] = defaultdict(int)
        for fact in coaching_facts:
            source_session = session_map.get(fact.session_id)
            if not source_session:
                continue
            note = note_map.get(fact.coaching_note_id)
            delta = round(fact.score_delta, 2) if fact.score_delta is not None else None
            outcome = "unmeasured"
            if delta is not None:
                if delta > 0.3:
                    outcome = "improved"
                elif delta < -0.3:
                    outcome = "regressed"
                else:
                    outcome = "flat"
                for tag in fact.weakness_tags_json or []:
                    rollup = tag_rollups[tag]
                    rollup["deltas"].append(delta)
                    if outcome == "improved":
                        rollup["improved_count"] += 1
                    elif outcome == "regressed":
                        rollup["regressed_count"] += 1
                    else:
                        rollup["flat_count"] += 1
            segment_key = ("visible" if fact.visible_to_rep else "internal", outcome)
            intervention_segments[segment_key] += 1
            uplift_rows.append(
                {
                    "rep_id": source_session.rep_id,
                    "rep_name": source_session.rep_name,
                    "session_id": source_session.session_id,
                    "focus_turn_id": source_session.focus_turn_id,
                    "next_session_id": fact.next_session_id,
                    "scenario_name": source_session.scenario_name,
                    "before_score": fact.before_score,
                    "after_score": fact.after_score,
                    "delta": delta,
                    "outcome": outcome,
                    "visible_to_rep": bool(fact.visible_to_rep),
                    "note": note.note if note else "",
                    "weakness_tags": list(fact.weakness_tags_json or []),
                    "created_at": fact.note_created_at.isoformat(),
                }
            )
            recent_notes.append(
                {
                    "id": fact.coaching_note_id,
                    "rep_id": source_session.rep_id,
                    "rep_name": source_session.rep_name,
                    "scenario_name": source_session.scenario_name,
                    "session_id": source_session.session_id,
                    "focus_turn_id": source_session.focus_turn_id,
                    "note": note.note if note else "",
                    "visible_to_rep": bool(fact.visible_to_rep),
                    "weakness_tags": list(fact.weakness_tags_json or []),
                    "delta": delta,
                    "outcome": outcome,
                    "created_at": fact.note_created_at.isoformat(),
                }
            )

        reviewer_rows: dict[str, dict[str, Any]] = {}
        override_deltas = []
        for review in calibration_facts:
            row = reviewer_rows.setdefault(
                review.reviewer_id,
                {
                    "reviewer_id": review.reviewer_id,
                    "review_count": 0,
                    "override_count": 0,
                    "average_override_delta": None,
                    "harsh_adjustments": 0,
                    "lenient_adjustments": 0,
                    "delta_samples": [],
                },
            )
            row["review_count"] += 1
            if review.override_score is not None and review.ai_score is not None and review.delta_score is not None:
                delta = round(review.delta_score, 2)
                row["override_count"] += 1
                row["delta_samples"].append(delta)
                override_deltas.append(delta)
                if delta >= 0:
                    row["lenient_adjustments"] += 1
                else:
                    row["harsh_adjustments"] += 1

        reviewers = []
        for reviewer_id, row in reviewer_rows.items():
            reviewer = db.scalar(select(User).where(User.id == reviewer_id))
            avg_delta = round(sum(row["delta_samples"]) / len(row["delta_samples"]), 2) if row["delta_samples"] else None
            avg_abs_delta = round(sum(abs(delta) for delta in row["delta_samples"]) / len(row["delta_samples"]), 2) if row["delta_samples"] else None
            reviewers.append(
                {
                    "reviewer_id": reviewer_id,
                    "reviewer_name": reviewer.name if reviewer else reviewer_id,
                    "review_count": row["review_count"],
                    "override_count": row["override_count"],
                    "average_override_delta": avg_delta,
                    "absolute_average_delta": avg_abs_delta,
                    "bias_direction": "lenient" if avg_delta and avg_delta > 0 else "harsh" if avg_delta and avg_delta < 0 else "neutral",
                    "harsh_adjustments": row["harsh_adjustments"],
                    "lenient_adjustments": row["lenient_adjustments"],
                }
            )
        reviewers.sort(key=lambda item: item["review_count"], reverse=True)

        timeline_buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"date": "", "review_count": 0, "coaching_note_count": 0})
        for review in calibration_facts:
            key = review.reviewed_at.date().isoformat()
            timeline_buckets[key]["date"] = key
            timeline_buckets[key]["review_count"] += 1
        for fact in coaching_facts:
            key = fact.note_created_at.date().isoformat()
            timeline_buckets[key]["date"] = key
            timeline_buckets[key]["coaching_note_count"] += 1

        retry_rows = []
        retry_deltas: list[float] = []
        coached_retry_deltas: list[float] = []
        sessions_by_rep_scenario: dict[tuple[str, str], list[SessionRecord]] = defaultdict(list)
        for session in sessions:
            if session.overall_score is not None:
                sessions_by_rep_scenario[(session.rep_id, session.scenario_id)].append(session)

        coached_pairs = {
            (fact.session_id, fact.next_session_id)
            for fact in coaching_facts
            if fact.next_session_id and fact.score_delta is not None
        }
        for items in sessions_by_rep_scenario.values():
            items.sort(key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc))
            for previous, current in zip(items, items[1:]):
                if previous.overall_score is None or current.overall_score is None:
                    continue
                delta = round(current.overall_score - previous.overall_score, 2)
                coached = (previous.session_id, current.session_id) in coached_pairs
                retry_deltas.append(delta)
                if coached:
                    coached_retry_deltas.append(delta)
                retry_rows.append(
                    {
                        "rep_id": current.rep_id,
                        "rep_name": current.rep_name,
                        "scenario_id": current.scenario_id,
                        "scenario_name": current.scenario_name,
                        "from_session_id": previous.session_id,
                        "to_session_id": current.session_id,
                        "before_score": previous.overall_score,
                        "after_score": current.overall_score,
                        "delta": delta,
                        "coached_between_attempts": coached,
                        "days_between": (
                            max(
                                0,
                                int(
                                    (
                                        (current.started_at or datetime.min.replace(tzinfo=timezone.utc))
                                        - (previous.started_at or datetime.min.replace(tzinfo=timezone.utc))
                                    ).total_seconds()
                                    / 86400
                                ),
                            )
                            if current.started_at and previous.started_at
                            else None
                        ),
                    }
                )

        calibration_drift_timeline_map: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"date": "", "review_count": 0, "average_delta": None, "average_absolute_delta": None, "_deltas": []}
        )
        scenario_drift_map: dict[str, dict[str, Any]] = {}
        for review in calibration_facts:
            if review.delta_score is None:
                continue
            timeline_key = review.reviewed_at.date().isoformat()
            timeline_row = calibration_drift_timeline_map[timeline_key]
            timeline_row["date"] = timeline_key
            timeline_row["review_count"] += 1
            timeline_row["_deltas"].append(float(review.delta_score))

            source_session = session_map.get(review.session_id)
            scenario_key = source_session.scenario_id if source_session else "unknown"
            scenario_row = scenario_drift_map.setdefault(
                scenario_key,
                {
                    "scenario_id": scenario_key,
                    "scenario_name": source_session.scenario_name if source_session else "Unknown",
                    "review_count": 0,
                    "delta_samples": [],
                },
            )
            scenario_row["review_count"] += 1
            scenario_row["delta_samples"].append(float(review.delta_score))

        calibration_drift_timeline = []
        for key in sorted(calibration_drift_timeline_map):
            row = calibration_drift_timeline_map[key]
            deltas = row.pop("_deltas")
            row["average_delta"] = round(sum(deltas) / len(deltas), 2) if deltas else None
            row["average_absolute_delta"] = round(sum(abs(delta) for delta in deltas) / len(deltas), 2) if deltas else None
            calibration_drift_timeline.append(row)

        score_drift_by_scenario = []
        for row in scenario_drift_map.values():
            deltas = row.pop("delta_samples")
            score_drift_by_scenario.append(
                {
                    **row,
                    "average_delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
                    "average_absolute_delta": round(sum(abs(delta) for delta in deltas) / len(deltas), 2) if deltas else None,
                }
            )
        score_drift_by_scenario.sort(key=lambda item: item["average_absolute_delta"] or 0, reverse=True)

        measured_interventions = [row for row in coaching_facts if row.score_delta is not None]
        improved_interventions = [row for row in measured_interventions if row.score_delta is not None and row.score_delta > 0.3]

        return {
            "manager_id": manager_id,
            "period": period,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "summary": {
                "coaching_note_count": len(coaching_facts),
                "review_count": len(calibration_facts),
                "override_rate": round(
                    len([review for review in calibration_facts if review.override_score is not None]) / max(1, len(calibration_facts)),
                    3,
                ) if calibration_facts else 0.0,
                "average_override_delta": round(sum(override_deltas) / len(override_deltas), 2) if override_deltas else None,
                "calibration_drift_score": round(sum(abs(delta) for delta in override_deltas) / len(override_deltas), 2) if override_deltas else None,
                "intervention_improved_rate": round(len(improved_interventions) / len(measured_interventions), 3) if measured_interventions else None,
                "retry_uplift_avg": round(sum(retry_deltas) / len(retry_deltas), 2) if retry_deltas else None,
                "coached_retry_uplift_avg": round(sum(coached_retry_deltas) / len(coached_retry_deltas), 2) if coached_retry_deltas else None,
            },
            "coaching_uplift": uplift_rows[:36],
            "weakness_tag_uplift": [
                {
                    "tag": tag,
                    "delta": round(sum(values["deltas"]) / len(values["deltas"]), 2),
                    "sample_size": len(values["deltas"]),
                    "improved_count": values["improved_count"],
                    "flat_count": values["flat_count"],
                    "regressed_count": values["regressed_count"],
                }
                for tag, values in sorted(
                    tag_rollups.items(),
                    key=lambda item: (sum(item[1]["deltas"]) / len(item[1]["deltas"])) if item[1]["deltas"] else 0,
                    reverse=True,
                )
                if values["deltas"]
            ],
            "manager_calibration": reviewers,
            "intervention_timeline": [timeline_buckets[key] for key in sorted(timeline_buckets)],
            "calibration_drift_timeline": calibration_drift_timeline,
            "retry_impact": retry_rows[:36],
            "intervention_segments": [
                {
                    "visibility": visibility,
                    "outcome": outcome,
                    "count": count,
                }
                for (visibility, outcome), count in sorted(intervention_segments.items())
            ],
            "score_drift_by_scenario": score_drift_by_scenario[:12],
            "recent_notes": recent_notes[:20],
        }

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
        sessions = self._load_sessions(db, manager_id=manager_id, date_from=date_from, date_to=date_to)
        session_ids = [session.session_id for session in sessions]
        objection_tags = self._load_objection_tags(db, session_ids)
        transcript_previews = self._load_transcript_previews(db, session_ids)
        barge_in_counts = self._load_barge_in_counts(db, session_ids)

        items = []
        needle = search.lower().strip() if search else None
        for session in sessions:
            if rep_id and session.rep_id != rep_id:
                continue
            if scenario_id and session.scenario_id != scenario_id:
                continue
            if reviewed is True and not session.manager_reviewed:
                continue
            if reviewed is False and session.manager_reviewed:
                continue
            if weakness_tag and weakness_tag not in session.weakness_tags:
                continue
            if score_min is not None and (session.overall_score is None or session.overall_score < score_min):
                continue
            if score_max is not None and (session.overall_score is None or session.overall_score > score_max):
                continue
            barge_in_count = int(barge_in_counts.get(session.session_id, 0))
            if barge_in_only and barge_in_count <= 0:
                continue
            preview = transcript_previews.get(session.session_id, "")
            if needle:
                searchable = f"{session.rep_name} {session.scenario_name} {preview} {' '.join(session.weakness_tags)}".lower()
                if needle not in searchable:
                    continue
            items.append(
                {
                    "session_id": session.session_id,
                    "rep_id": session.rep_id,
                    "rep_name": session.rep_name,
                    "scenario_id": session.scenario_id,
                    "scenario_name": session.scenario_name,
                    "started_at": session.started_at.isoformat() if session.started_at else None,
                    "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                    "duration_seconds": session.duration_seconds,
                    "overall_score": session.overall_score,
                    "manager_reviewed": session.manager_reviewed,
                    "latest_reviewed_at": session.latest_reviewed_at.isoformat() if session.latest_reviewed_at else None,
                    "latest_coaching_note_preview": session.latest_coaching_note_preview,
                    "weakness_tags": session.weakness_tags,
                    "objection_tags": objection_tags.get(session.session_id, []),
                    "barge_in_count": barge_in_count,
                    "highlight_count": len(session.highlights),
                    "transcript_preview": preview,
                    "assignment_status": session.assignment_status,
                    "session_status": session.session_status,
                    "focus_turn_id": session.focus_turn_id,
                }
            )
        items = items[:limit]
        return {
            "manager_id": manager_id,
            "items": items,
            "total_count": len(items),
            "filters": {
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
        }

    def get_alerts(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        command_center = self.get_command_center(
            db,
            manager_id=manager_id,
            date_from=date_from,
            date_to=date_to,
            previous_start=date_from,
            previous_end=date_to,
            period=period,
        )
        return {
            "manager_id": manager_id,
            "period": period,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "items": command_center["alerts_preview"],
        }

    def get_benchmarks(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime,
        date_to: datetime,
        period: str,
    ) -> dict[str, Any]:
        materialized = self._get_materialized_payload(db, manager_id=manager_id, view_name="benchmarks", period=period)
        if materialized is not None:
            return materialized
        sessions = self._load_sessions(db, manager_id=manager_id, date_from=date_from, date_to=date_to)
        scores = sorted(session.overall_score for session in sessions if session.overall_score is not None)
        if scores:
            median = scores[len(scores) // 2]
            top_quartile = scores[max(0, int(len(scores) * 0.75) - 1)]
            lower_quartile = scores[max(0, int(len(scores) * 0.25) - 1)]
        else:
            median = top_quartile = lower_quartile = None
        return {
            "manager_id": manager_id,
            "period": period,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "score_benchmarks": {
                "median": median,
                "upper_quartile": top_quartile,
                "lower_quartile": lower_quartile,
                "session_count": len(scores),
            },
        }
