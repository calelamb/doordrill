from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.grading_service import GradingService
from app.services.notification_service import NotificationService
from app.services.transcript_cleanup_service import TranscriptCleanupService
from app.tasks.celery_app import get_celery_app

logger = logging.getLogger(__name__)


class SessionPostprocessService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cleanup_service = TranscriptCleanupService()
        self.grading_service = GradingService()
        self.notification_service = NotificationService()

    async def run_inline(self, db: Session, session_id: str) -> dict[str, Any]:
        cleanup_artifact = await self.cleanup_service.cleanup_session_transcript(db, session_id)
        scorecard = await self.grading_service.grade_session(db, session_id=session_id)
        notification = await self.notification_service.notify_manager_session_completed(db, session_id)
        return {
            "mode": "inline",
            "cleanup_artifact_id": cleanup_artifact.id,
            "scorecard_id": scorecard.id,
            "notification": notification,
        }

    async def enqueue_or_run(self, db: Session, session_id: str) -> dict[str, Any]:
        if self.settings.use_celery:
            celery = get_celery_app()
            if celery is not None:
                try:
                    celery.send_task("post_session.cleanup_transcript", args=[session_id])
                    celery.send_task("post_session.grade_session", args=[session_id])
                    celery.send_task("post_session.notify_manager", args=[session_id])
                    return {"mode": "celery", "session_id": session_id}
                except Exception:
                    logger.exception("Failed to enqueue post-session tasks, falling back inline", extra={"session_id": session_id})
        return await self.run_inline(db, session_id)
