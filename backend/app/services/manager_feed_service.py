from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.scorecard import ManagerReview, Scorecard
from app.models.session import Session as DrillSession


class ManagerFeedService:
    def get_feed(self, db: Session, manager_id: str) -> list[dict]:
        assignments = db.scalars(select(Assignment).where(Assignment.assigned_by == manager_id)).all()
        items: list[dict] = []
        for assignment in assignments:
            sessions = db.scalars(
                select(DrillSession)
                .where(DrillSession.assignment_id == assignment.id)
                .order_by(DrillSession.created_at.desc())
            ).all()
            for session in sessions:
                scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session.id))
                reviewed = False
                if scorecard:
                    reviewed = db.scalar(select(ManagerReview).where(ManagerReview.scorecard_id == scorecard.id)) is not None
                items.append(
                    {
                        "session_id": session.id,
                        "rep_id": session.rep_id,
                        "assignment_id": assignment.id,
                        "overall_score": scorecard.overall_score if scorecard else None,
                        "category_scores": scorecard.category_scores if scorecard else {},
                        "highlights": scorecard.highlights if scorecard else [],
                        "manager_reviewed": reviewed,
                        "assignment_status": assignment.status.value,
                        "session_status": session.status.value,
                    }
                )
        return items
