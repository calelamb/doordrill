from __future__ import annotations

import asyncio

from app.db.session import SessionLocal
from app.services.notification_service import NotificationService
from app.services.session_postprocess_service import SessionPostprocessService
from app.tasks.celery_app import get_celery_app

celery_app = get_celery_app()
postprocess_service = SessionPostprocessService()
notification_service = NotificationService()


def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _run_task(session_id: str, task_type: str):
    db = SessionLocal()
    try:
        return _run(postprocess_service.run_task_inline(db, session_id=session_id, task_type=task_type))
    finally:
        db.close()


def _run_postprocess_retry(limit: int):
    db = SessionLocal()
    try:
        return _run(postprocess_service.retry_due_runs(db, limit=limit))
    finally:
        db.close()


def _run_notification_retry(limit: int):
    db = SessionLocal()
    try:
        return _run(notification_service.retry_due_deliveries(db, limit=limit))
    finally:
        db.close()


if celery_app is not None:  # pragma: no branch - depends on runtime settings
    @celery_app.task(bind=True, name="post_session.cleanup", max_retries=5)
    def cleanup_task(self, session_id: str):
        try:
            result = _run_task(session_id, "cleanup")
            return {"ok": True, "task": "cleanup", "session_id": session_id, "result": result}
        except Exception as exc:  # pragma: no cover - worker runtime
            if self.request.retries >= self.max_retries:
                return {"ok": False, "task": "cleanup", "session_id": session_id, "error": str(exc)}
            countdown = min(30 * (2 ** self.request.retries), 900)
            raise self.retry(exc=exc, countdown=countdown)


    @celery_app.task(bind=True, name="post_session.grade", max_retries=5)
    def grade_task(self, session_id: str):
        try:
            result = _run_task(session_id, "grade")
            return {"ok": True, "task": "grade", "session_id": session_id, "result": result}
        except Exception as exc:  # pragma: no cover - worker runtime
            if self.request.retries >= self.max_retries:
                return {"ok": False, "task": "grade", "session_id": session_id, "error": str(exc)}
            countdown = min(30 * (2 ** self.request.retries), 900)
            raise self.retry(exc=exc, countdown=countdown)


    @celery_app.task(bind=True, name="post_session.notify", max_retries=5)
    def notify_task(self, session_id: str):
        try:
            result = _run_task(session_id, "notify")
            return {"ok": True, "task": "notify", "session_id": session_id, "result": result}
        except Exception as exc:  # pragma: no cover - worker runtime
            if self.request.retries >= self.max_retries:
                return {"ok": False, "task": "notify", "session_id": session_id, "error": str(exc)}
            countdown = min(30 * (2 ** self.request.retries), 900)
            raise self.retry(exc=exc, countdown=countdown)


    @celery_app.task(bind=True, name="post_session.retry_due", max_retries=1)
    def retry_due_postprocess(self, limit: int = 50):
        try:
            result = _run_postprocess_retry(limit)
            return {"ok": True, "task": "post_session.retry_due", "result": result}
        except Exception as exc:  # pragma: no cover - worker runtime
            if self.request.retries >= self.max_retries:
                return {"ok": False, "task": "post_session.retry_due", "error": str(exc)}
            raise self.retry(exc=exc, countdown=30)


    @celery_app.task(bind=True, name="notifications.retry_due", max_retries=1)
    def retry_due_notifications(self, limit: int = 50):
        try:
            result = _run_notification_retry(limit)
            return {"ok": True, "task": "notifications.retry_due", "result": result}
        except Exception as exc:  # pragma: no cover - worker runtime
            if self.request.retries >= self.max_retries:
                return {"ok": False, "task": "notifications.retry_due", "error": str(exc)}
            raise self.retry(exc=exc, countdown=30)
