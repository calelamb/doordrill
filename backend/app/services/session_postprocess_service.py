from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.postprocess_run import PostprocessRun
from app.services.grading_service import GradingService
from app.services.notification_service import NotificationService
from app.services.transcript_cleanup_service import TranscriptCleanupService
from app.tasks.celery_app import get_celery_app

logger = logging.getLogger(__name__)
TASK_TYPES = ("cleanup", "grade", "notify")


class SessionPostprocessService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cleanup_service = TranscriptCleanupService()
        self.grading_service = GradingService()
        self.notification_service = NotificationService()

    def _ensure_run_row(self, db: Session, *, session_id: str, task_type: str) -> PostprocessRun:
        row = db.scalar(
            select(PostprocessRun).where(PostprocessRun.session_id == session_id, PostprocessRun.task_type == task_type)
        )
        if row:
            return row

        row = PostprocessRun(
            session_id=session_id,
            task_type=task_type,
            status="pending",
            attempts=0,
            idempotency_key=f"{session_id}:{task_type}",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def _queue_task(self, db: Session, *, session_id: str, task_type: str) -> bool:
        row = self._ensure_run_row(db, session_id=session_id, task_type=task_type)
        row.status = "queued"
        row.next_retry_at = None
        db.commit()

        celery = get_celery_app()
        if celery is None:
            return False
        queue_name = f"postprocess.{task_type}"
        celery.send_task(f"post_session.{task_type}", args=[session_id], queue=queue_name)
        return True

    async def run_task_inline(self, db: Session, *, session_id: str, task_type: str) -> dict[str, Any]:
        if task_type not in TASK_TYPES:
            raise ValueError(f"unsupported task_type: {task_type}")

        row = self._ensure_run_row(db, session_id=session_id, task_type=task_type)
        if row.status == "completed":
            return {"task_type": task_type, "status": "already_completed", "run_id": row.id}

        row.status = "running"
        row.attempts = int(row.attempts) + 1
        row.last_error = None
        row.next_retry_at = None
        db.commit()

        try:
            if task_type == "cleanup":
                result = await self.cleanup_service.cleanup_session_transcript(db, session_id)
                payload = {"artifact_id": result.id}
            elif task_type == "grade":
                result = await self.grading_service.grade_session(db, session_id=session_id)
                payload = {"scorecard_id": result.id}
            else:
                result = await self.notification_service.notify_manager_session_completed(db, session_id)
                payload = {"notification": result}

            row.status = "completed"
            row.completed_at = datetime.now(timezone.utc)
            db.commit()
            return {"task_type": task_type, "status": "completed", "run_id": row.id, **payload}
        except Exception as exc:
            row.status = "retry_scheduled" if row.attempts < self.settings.notification_max_retries else "failed"
            row.last_error = str(exc)[:1000]
            if row.status == "retry_scheduled":
                delay = self.settings.notification_retry_base_seconds * (2 ** max(0, row.attempts - 1))
                row.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=min(delay, 3600))
            else:
                row.next_retry_at = None
            db.commit()
            raise

    async def run_inline(self, db: Session, session_id: str) -> dict[str, Any]:
        cleanup_result = await self.run_task_inline(db, session_id=session_id, task_type="cleanup")
        grade_result = await self.run_task_inline(db, session_id=session_id, task_type="grade")
        notify_result = await self.run_task_inline(db, session_id=session_id, task_type="notify")
        return {
            "mode": "inline",
            "cleanup": cleanup_result,
            "grade": grade_result,
            "notify": notify_result,
        }

    async def enqueue_or_run(self, db: Session, session_id: str) -> dict[str, Any]:
        if self.settings.use_celery:
            try:
                queued = 0
                for task_type in TASK_TYPES:
                    queued += int(self._queue_task(db, session_id=session_id, task_type=task_type))
                if queued == len(TASK_TYPES):
                    return {"mode": "celery", "session_id": session_id}
            except Exception:
                logger.exception("Failed to enqueue post-session tasks, falling back inline", extra={"session_id": session_id})
        return await self.run_inline(db, session_id)

    async def retry_due_runs(self, db: Session, *, limit: int = 50) -> dict[str, Any]:
        stmt = (
            select(PostprocessRun)
            .where(
                PostprocessRun.status == "retry_scheduled",
                PostprocessRun.next_retry_at.is_not(None),
                PostprocessRun.next_retry_at <= datetime.now(timezone.utc),
            )
            .order_by(PostprocessRun.next_retry_at.asc())
            .limit(limit)
        )
        bind = db.get_bind()
        if bind is not None and bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update(skip_locked=True)

        rows = db.scalars(stmt).all()
        items: list[dict[str, Any]] = []
        for row in rows:
            if row.status == "completed":
                continue
            if self.settings.use_celery and get_celery_app() is not None:
                self._queue_task(db, session_id=row.session_id, task_type=row.task_type)
                items.append({"run_id": row.id, "task_type": row.task_type, "status": "queued"})
                continue

            result = await self.run_task_inline(db, session_id=row.session_id, task_type=row.task_type)
            items.append({"run_id": row.id, **result})

        return {"retried_count": len(items), "items": items}
