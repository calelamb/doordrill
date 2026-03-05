from __future__ import annotations

import asyncio

from app.db.session import SessionLocal
from app.services.grading_service import GradingService
from app.services.notification_service import NotificationService
from app.services.transcript_cleanup_service import TranscriptCleanupService
from app.tasks.celery_app import get_celery_app

celery_app = get_celery_app()
grading_service = GradingService()
cleanup_service = TranscriptCleanupService()
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


def _cleanup(session_id: str):
    db = SessionLocal()
    try:
        return _run(cleanup_service.cleanup_session_transcript(db, session_id))
    finally:
        db.close()


def _grade(session_id: str):
    db = SessionLocal()
    try:
        return _run(grading_service.grade_session(db, session_id))
    finally:
        db.close()


def _notify(session_id: str):
    db = SessionLocal()
    try:
        return _run(notification_service.notify_manager_session_completed(db, session_id))
    finally:
        db.close()


if celery_app is not None:  # pragma: no branch - depends on runtime settings
    @celery_app.task(name="post_session.cleanup_transcript")
    def cleanup_transcript_task(session_id: str):
        _cleanup(session_id)
        return {"ok": True, "task": "cleanup_transcript", "session_id": session_id}


    @celery_app.task(name="post_session.grade_session")
    def grade_session_task(session_id: str):
        _grade(session_id)
        return {"ok": True, "task": "grade_session", "session_id": session_id}


    @celery_app.task(name="post_session.notify_manager")
    def notify_manager_task(session_id: str):
        _notify(session_id)
        return {"ok": True, "task": "notify_manager", "session_id": session_id}
