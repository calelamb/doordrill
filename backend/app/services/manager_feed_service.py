from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.scorecard import ManagerReview, Scorecard
from app.models.session import Session as DrillSession


class ManagerFeedService:
    def get_feed(self, db: Session, manager_id: str) -> list[dict]:
        reviewed_exists = (
            select(ManagerReview.id)
            .where(ManagerReview.scorecard_id == Scorecard.id)
            .limit(1)
            .correlate(Scorecard)
            .exists()
        )

        stmt = (
            select(
                DrillSession.id.label("session_id"),
                DrillSession.rep_id.label("rep_id"),
                DrillSession.status.label("session_status"),
                Assignment.id.label("assignment_id"),
                Assignment.status.label("assignment_status"),
                Scorecard.overall_score.label("overall_score"),
                Scorecard.category_scores.label("category_scores"),
                Scorecard.highlights.label("highlights"),
                case((reviewed_exists, True), else_=False).label("manager_reviewed"),
            )
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(Assignment.assigned_by == manager_id)
            .order_by(DrillSession.created_at.desc())
        )

        rows = db.execute(stmt).mappings().all()
        return [
            {
                "session_id": row["session_id"],
                "rep_id": row["rep_id"],
                "assignment_id": row["assignment_id"],
                "overall_score": row["overall_score"],
                "category_scores": row["category_scores"] or {},
                "highlights": row["highlights"] or [],
                "manager_reviewed": bool(row["manager_reviewed"]),
                "assignment_status": row["assignment_status"].value,
                "session_status": row["session_status"].value,
            }
            for row in rows
        ]
