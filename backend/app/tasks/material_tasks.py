from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.org_material import OrgMaterial
from app.services.material_extraction_service import MaterialExtractionService
from app.tasks.celery_app import get_celery_app

celery_app = get_celery_app()
material_extraction_service = MaterialExtractionService()


def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _mark_failed(material_id: int, error: str) -> None:
    db = SessionLocal()
    try:
        material = db.scalar(select(OrgMaterial).where(OrgMaterial.id == material_id))
        if material is None:
            return
        material.extraction_status = "failed"
        material.extraction_error = error[:4000]
        db.commit()
    finally:
        db.close()


def _run_material_process(material_id: int) -> None:
    db = SessionLocal()
    try:
        _run(material_extraction_service.process(material_id=material_id, db=db))
    finally:
        db.close()


async def _run_material_process_async(material_id: int) -> None:
    db = SessionLocal()
    try:
        await material_extraction_service.process(material_id=material_id, db=db)
    finally:
        db.close()


def enqueue_material_processing(material_id: int):
    if celery_app is not None:
        return process_material.delay(material_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _run_material_process(material_id)
    return loop.create_task(_run_material_process_async(material_id))


if celery_app is not None:  # pragma: no branch - worker runtime only
    @celery_app.task(bind=True, name="materials.process", max_retries=3, default_retry_delay=30)
    def process_material(self, material_id: int):
        try:
            _run_material_process(material_id)
            return {"ok": True, "material_id": material_id}
        except Exception as exc:  # pragma: no cover - worker runtime
            _mark_failed(material_id, str(exc))
            if self.request.retries >= self.max_retries:
                return {"ok": False, "material_id": material_id, "error": str(exc)}
            raise self.retry(exc=exc, countdown=30)

else:
    class _InlineProcessMaterialTask:
        def delay(self, material_id: int):
            return enqueue_material_processing(material_id)


    process_material = _InlineProcessMaterialTask()
