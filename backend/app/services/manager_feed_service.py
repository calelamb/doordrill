from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.user import User


class ManagerFeedService:
    def get_feed(
        self,
        db: Session,
        *,
        manager_id: str,
        rep_id: str | None = None,
        scenario_id: str | None = None,
        reviewed: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
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
                DrillSession.status.label("session_status"),
                DrillSession.scenario_id.label("scenario_id"),
                Scenario.name.label("scenario_name"),
                DrillSession.started_at.label("started_at"),
                DrillSession.ended_at.label("ended_at"),
                DrillSession.duration_seconds.label("duration_seconds"),
                Assignment.id.label("assignment_id"),
                Assignment.status.label("assignment_status"),
                Scorecard.overall_score.label("overall_score"),
                Scorecard.category_scores.label("category_scores"),
                Scorecard.highlights.label("highlights"),
                case((reviewed_exists, True), else_=False).label("manager_reviewed"),
                latest_reviewed_at.label("latest_reviewed_at"),
                latest_coaching_note.label("latest_coaching_note_preview"),
            )
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .join(User, User.id == DrillSession.rep_id)
            .join(Scenario, Scenario.id == DrillSession.scenario_id)
            .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(Assignment.assigned_by == manager_id)
            .order_by(DrillSession.created_at.desc())
            .limit(limit)
        )
        if rep_id:
            stmt = stmt.where(DrillSession.rep_id == rep_id)
        if scenario_id:
            stmt = stmt.where(DrillSession.scenario_id == scenario_id)
        if reviewed is True:
            stmt = stmt.where(reviewed_exists)
        elif reviewed is False:
            stmt = stmt.where(~reviewed_exists)
        if date_from:
            stmt = stmt.where(DrillSession.started_at >= date_from)
        if date_to:
            stmt = stmt.where(DrillSession.started_at <= date_to)

        rows = db.execute(stmt).mappings().all()
        return [
            {
                "session_id": row["session_id"],
                "rep_id": row["rep_id"],
                "rep_name": row["rep_name"],
                "assignment_id": row["assignment_id"],
                "scenario_id": row["scenario_id"],
                "scenario_name": row["scenario_name"],
                "overall_score": row["overall_score"],
                "category_scores": row["category_scores"] or {},
                "highlights": row["highlights"] or [],
                "manager_reviewed": bool(row["manager_reviewed"]),
                "assignment_status": row["assignment_status"].value,
                "session_status": row["session_status"].value,
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "ended_at": row["ended_at"].isoformat() if row["ended_at"] else None,
                "duration_seconds": row["duration_seconds"],
                "latest_reviewed_at": row["latest_reviewed_at"].isoformat() if row["latest_reviewed_at"] else None,
                "latest_coaching_note_preview": row["latest_coaching_note_preview"],
            }
            for row in rows
        ]
