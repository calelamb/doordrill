from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings

try:  # pragma: no cover - optional runtime dependency
    from celery import Celery
    from celery.schedules import crontab
except Exception:  # pragma: no cover
    Celery = None  # type: ignore[assignment]
    crontab = None  # type: ignore[assignment]


@lru_cache(maxsize=1)
def get_celery_app():
    settings = get_settings()
    if not settings.use_celery or Celery is None:
        return None

    celery_app = Celery(
        "doordrill",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    celery_app.conf.task_serializer = "json"
    celery_app.conf.result_serializer = "json"
    celery_app.conf.accept_content = ["json"]
    celery_app.conf.timezone = "UTC"
    celery_app.conf.task_routes = {
        "materials.process": {"queue": "materials.process"},
        "post_session.cleanup": {"queue": "postprocess.cleanup"},
        "post_session.grade": {"queue": "postprocess.grade"},
        "post_session.notify": {"queue": "postprocess.notify"},
        "post_session.retry_due": {"queue": "postprocess.retry"},
        "notifications.retry_due": {"queue": "notifications.retry"},
        "notifications.assignment_due_soon": {"queue": "notifications.scheduled"},
        "notifications.streak_nudges": {"queue": "notifications.scheduled"},
        "analytics.refresh_manager": {"queue": "analytics.refresh"},
        "analytics.backfill": {"queue": "analytics.backfill"},
    }
    celery_app.conf.task_acks_late = True
    celery_app.conf.worker_prefetch_multiplier = 1
    celery_app.conf.beat_schedule = {
        "post-session-retry-due-every-minute": {
            "task": "post_session.retry_due",
            "schedule": 60.0,
        },
        "notifications-retry-due-every-minute": {
            "task": "notifications.retry_due",
            "schedule": 60.0,
        },
        "analytics-backfill-hourly": {
            "task": "analytics.backfill",
            "schedule": 3600.0,
        },
    }
    if crontab is not None:
        celery_app.conf.beat_schedule.update(
            {
                "assignment-due-soon-reminders": {
                    "task": "notifications.assignment_due_soon",
                    "schedule": crontab(minute=0, hour="*/1"),
                },
                "streak-nudges-daily": {
                    "task": "notifications.streak_nudges",
                    "schedule": crontab(minute=0, hour=18),
                },
            }
        )
    return celery_app
