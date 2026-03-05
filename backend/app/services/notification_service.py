from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session
from app.models.user import User

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def notify_manager_session_completed(self, db: Session, session_id: str) -> dict:
        session = db.scalar(select(Session).where(Session.id == session_id))
        if session is None:
            return {"sent": False, "reason": "session_not_found"}

        assignment = db.scalar(select(Assignment).where(Assignment.id == session.assignment_id))
        if assignment is None:
            return {"sent": False, "reason": "assignment_not_found"}

        manager = db.scalar(select(User).where(User.id == assignment.assigned_by))
        rep = db.scalar(select(User).where(User.id == session.rep_id))
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        if manager is None:
            return {"sent": False, "reason": "manager_not_found"}

        summary = (
            f"Session {session_id} completed for rep {rep.name if rep else session.rep_id}; "
            f"score={scorecard.overall_score if scorecard else 'pending'}"
        )
        logger.info(
            "manager_session_notification",
            extra={
                "session_id": session_id,
                "manager_id": manager.id,
                "manager_email": manager.email,
                "summary": summary,
                "email_enabled": self.settings.manager_notification_email_enabled,
            },
        )
        return {
            "sent": bool(self.settings.manager_notification_email_enabled),
            "channel": "email" if self.settings.manager_notification_email_enabled else "log_only",
            "manager_id": manager.id,
            "manager_email": manager.email,
            "summary": summary,
        }
