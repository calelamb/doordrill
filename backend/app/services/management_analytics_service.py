from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
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


class ManagementAnalyticsService:
    def _load_sessions(
        self,
        db: Session,
        *,
        manager_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[SessionRecord]:
        reviewed_exists = (
            select(ManagerReview.id)
            .where(ManagerReview.scorecard_id == Scorecard.id)
            .limit(1)
            .correlate(Scorecard)
            .exists()
        )
        latest_reviewed_at = (
            select(func.max(ManagerReview.reviewed_at))
            .where(ManagerReview.scorecard_id == Scorecard.id)
            .correlate(Scorecard)
            .scalar_subquery()
        )
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
                DrillSession.id.label("session_id"),
                DrillSession.rep_id.label("rep_id"),
                User.name.label("rep_name"),
                DrillSession.scenario_id.label("scenario_id"),
                Scenario.name.label("scenario_name"),
                Scenario.difficulty.label("scenario_difficulty"),
                DrillSession.started_at.label("started_at"),
                DrillSession.ended_at.label("ended_at"),
                DrillSession.duration_seconds.label("duration_seconds"),
                Scorecard.overall_score.label("overall_score"),
                Scorecard.category_scores.label("category_scores"),
                Scorecard.weakness_tags.label("weakness_tags"),
                Scorecard.highlights.label("highlights"),
                case((reviewed_exists, True), else_=False).label("manager_reviewed"),
                latest_reviewed_at.label("latest_reviewed_at"),
                latest_coaching_note.label("latest_coaching_note_preview"),
                Assignment.status.label("assignment_status"),
                DrillSession.status.label("session_status"),
            )
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .join(User, User.id == DrillSession.rep_id)
            .join(Scenario, Scenario.id == DrillSession.scenario_id)
            .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(Assignment.assigned_by == manager_id)
            .order_by(DrillSession.started_at.desc())
        )
        if date_from is not None:
            stmt = stmt.where(DrillSession.started_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(DrillSession.started_at <= date_to)

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
                category_scores=row["category_scores"] or {},
                weakness_tags=row["weakness_tags"] or [],
                highlights=row["highlights"] or [],
                manager_reviewed=bool(row["manager_reviewed"]),
                latest_reviewed_at=_normalize_dt(row["latest_reviewed_at"]),
                latest_coaching_note_preview=row["latest_coaching_note_preview"],
                assignment_status=row["assignment_status"].value if row["assignment_status"] else "unknown",
                session_status=row["session_status"].value if row["session_status"] else "unknown",
            )
            for row in rows
        ]

    def _load_objection_tags(self, db: Session, session_ids: list[str]) -> dict[str, list[str]]:
        if not session_ids:
            return {}
        rows = db.execute(
            select(SessionTurn.session_id, SessionTurn.objection_tags).where(SessionTurn.session_id.in_(session_ids))
        ).all()
        tags_by_session: dict[str, Counter[str]] = defaultdict(Counter)
        for session_id, tags in rows:
            for tag in tags or []:
                tags_by_session[session_id][tag] += 1
        return {session_id: [tag for tag, _ in counter.most_common()] for session_id, counter in tags_by_session.items()}

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
            select(SessionEvent.session_id, SessionEvent.payload)
            .where(
                SessionEvent.session_id.in_(session_ids),
                SessionEvent.event_type == "server.session.state",
            )
        ).all()
        counts: dict[str, int] = defaultdict(int)
        for session_id, payload in rows:
            if isinstance(payload, dict) and payload.get("state") == "barge_in_detected":
                counts[session_id] += 1
        return counts

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
                }
            )

        rows.sort(key=lambda item: (item["risk_score"], -item["average_score"]), reverse=True)
        return rows[:limit]

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
                    "session_id": None,
                    "scenario_id": None,
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
                        "session_id": None,
                        "scenario_id": scenario["scenario_id"],
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
        sessions = self._load_sessions(db, manager_id=manager_id, date_from=date_from, date_to=date_to)
        previous_sessions = self._load_sessions(db, manager_id=manager_id, date_from=previous_start, date_to=previous_end)
        session_ids = [session.session_id for session in sessions]
        completion_rows = self._load_assignment_completion(db, manager_id=manager_id, date_from=date_from, date_to=date_to)

        scores = [session.overall_score for session in sessions if session.overall_score is not None]
        previous_scores = [session.overall_score for session in previous_sessions if session.overall_score is not None]
        avg_score = round(sum(scores) / len(scores), 2) if scores else None
        previous_avg = round(sum(previous_scores) / len(previous_scores), 2) if previous_scores else None

        category_values: dict[str, list[float]] = defaultdict(list)
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
                    },
                )
                group["session_count"] += 1
                group["scored_count"] += 1
                group["score_sum"] += session.overall_score
                if session.overall_score >= 7.0:
                    group["pass_count"] += 1

            for raw_key, normalized_key in RUBRIC_CATEGORY_KEYS.items():
                value = _score_value(session.category_scores.get(raw_key))
                if value is not None:
                    category_values[normalized_key].append(value)

        weakest_categories = [
            {
                "category": key,
                "average_score": round(sum(values) / len(values), 2),
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
        scorecard_rows = db.execute(
            select(Scorecard.id, Scorecard.session_id).where(Scorecard.session_id.in_(session_ids))
        ).all()
        scorecard_by_session = {session_id: scorecard_id for scorecard_id, session_id in scorecard_rows}
        scorecard_ids = [scorecard_id for scorecard_id, _ in scorecard_rows]

        reviews = db.scalars(
            select(ManagerReview)
            .where(ManagerReview.scorecard_id.in_(scorecard_ids), ManagerReview.reviewed_at >= date_from, ManagerReview.reviewed_at <= date_to)
            .order_by(ManagerReview.reviewed_at.desc())
        ).all() if scorecard_ids else []

        notes = db.scalars(
            select(ManagerCoachingNote)
            .where(
                ManagerCoachingNote.scorecard_id.in_(scorecard_ids),
                ManagerCoachingNote.created_at >= date_from,
                ManagerCoachingNote.created_at <= date_to,
            )
            .order_by(ManagerCoachingNote.created_at.desc())
        ).all() if scorecard_ids else []

        scored_sessions_by_rep: dict[str, list[SessionRecord]] = defaultdict(list)
        for session in sessions:
            if session.overall_score is not None:
                scored_sessions_by_rep[session.rep_id].append(session)
        for rep_sessions in scored_sessions_by_rep.values():
            rep_sessions.sort(key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc))

        uplift_rows = []
        tag_uplift: dict[str, list[float]] = defaultdict(list)
        recent_notes = []
        for note in notes:
            session_id = next((sid for sid, scid in scorecard_by_session.items() if scid == note.scorecard_id), None)
            if not session_id:
                continue
            source_session = session_map.get(session_id)
            if not source_session or source_session.overall_score is None:
                continue
            rep_sessions = scored_sessions_by_rep.get(source_session.rep_id, [])
            next_session = next((item for item in rep_sessions if (item.started_at or datetime.min.replace(tzinfo=timezone.utc)) > (source_session.started_at or datetime.min.replace(tzinfo=timezone.utc))), None)
            delta = None
            if next_session and next_session.overall_score is not None:
                delta = round(next_session.overall_score - source_session.overall_score, 2)
                for tag in note.weakness_tags:
                    tag_uplift[tag].append(delta)
            uplift_rows.append(
                {
                    "rep_id": source_session.rep_id,
                    "rep_name": source_session.rep_name,
                    "session_id": source_session.session_id,
                    "scenario_name": source_session.scenario_name,
                    "before_score": source_session.overall_score,
                    "after_score": next_session.overall_score if next_session else None,
                    "delta": delta,
                    "note": note.note,
                    "weakness_tags": note.weakness_tags,
                    "created_at": note.created_at.isoformat(),
                }
            )
            recent_notes.append(
                {
                    "id": note.id,
                    "rep_id": source_session.rep_id,
                    "rep_name": source_session.rep_name,
                    "scenario_name": source_session.scenario_name,
                    "note": note.note,
                    "visible_to_rep": note.visible_to_rep,
                    "weakness_tags": note.weakness_tags,
                    "created_at": note.created_at.isoformat(),
                }
            )

        reviewer_rows: dict[str, dict[str, Any]] = {}
        override_deltas = []
        for review in reviews:
            session_id = next((sid for sid, scid in scorecard_by_session.items() if scid == review.scorecard_id), None)
            source_session = session_map.get(session_id) if session_id else None
            base_score = source_session.overall_score if source_session else None
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
            if review.override_score is not None and base_score is not None:
                delta = round(review.override_score - base_score, 2)
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
            reviewers.append(
                {
                    "reviewer_id": reviewer_id,
                    "reviewer_name": reviewer.name if reviewer else reviewer_id,
                    "review_count": row["review_count"],
                    "override_count": row["override_count"],
                    "average_override_delta": round(sum(row["delta_samples"]) / len(row["delta_samples"]), 2) if row["delta_samples"] else None,
                    "harsh_adjustments": row["harsh_adjustments"],
                    "lenient_adjustments": row["lenient_adjustments"],
                }
            )
        reviewers.sort(key=lambda item: item["review_count"], reverse=True)

        timeline_buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"date": "", "review_count": 0, "coaching_note_count": 0})
        for review in reviews:
            key = review.reviewed_at.date().isoformat()
            timeline_buckets[key]["date"] = key
            timeline_buckets[key]["review_count"] += 1
        for note in notes:
            key = note.created_at.date().isoformat()
            timeline_buckets[key]["date"] = key
            timeline_buckets[key]["coaching_note_count"] += 1

        return {
            "manager_id": manager_id,
            "period": period,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "summary": {
                "coaching_note_count": len(notes),
                "review_count": len(reviews),
                "override_rate": round(
                    len([review for review in reviews if review.override_score is not None]) / max(1, len(reviews)),
                    3,
                ) if reviews else 0.0,
                "average_override_delta": round(sum(override_deltas) / len(override_deltas), 2) if override_deltas else None,
            },
            "coaching_uplift": uplift_rows[:36],
            "weakness_tag_uplift": [
                {
                    "tag": tag,
                    "delta": round(sum(values) / len(values), 2),
                    "sample_size": len(values),
                }
                for tag, values in sorted(tag_uplift.items(), key=lambda item: sum(item[1]) / len(item[1]), reverse=True)
                if values
            ],
            "manager_calibration": reviewers,
            "intervention_timeline": [timeline_buckets[key] for key in sorted(timeline_buckets)],
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
