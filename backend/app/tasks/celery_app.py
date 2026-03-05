from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings

try:  # pragma: no cover - optional runtime dependency
    from celery import Celery
except Exception:  # pragma: no cover
    Celery = None  # type: ignore[assignment]


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
    return celery_app
