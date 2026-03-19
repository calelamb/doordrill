from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.org_material import OrgKnowledgeDoc, OrgMaterial
from app.services.material_extraction_service import MaterialExtractionService
from app.services.storage_service import StorageService


def test_material_extraction_service_processes_txt_material(seed_org):
    db = SessionLocal()
    storage = StorageService()
    storage_key = f"tests/materials/{uuid4().hex}/guide.txt"
    storage.upload_bytes(
        storage_key,
        (
            "Common objection: homeowners worry that the monthly price is too expensive. "
            "Rebuttal: lead with monthly savings before discussing quote details. "
            "Our key advantage is a long warranty and faster local service. "
            "Competitor comparison: unlike Sunrun, we include battery backup options. "
            "Typical homeowner insight: suburban family homeowners care about trust and installation disruption. "
            "Pitch technique: start with a short door approach, then move into objection handling."
        ).encode("utf-8"),
        content_type="text/plain",
    )

    material = OrgMaterial(
        org_id=seed_org["org_id"],
        original_filename="guide.txt",
        file_type="txt",
        storage_key=storage_key,
        extraction_status="pending",
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    asyncio.run(MaterialExtractionService(storage_service=storage).process(material.id, db))

    refreshed = db.get(OrgMaterial, material.id)
    docs = db.scalars(
        select(OrgKnowledgeDoc)
        .where(OrgKnowledgeDoc.material_id == material.id)
        .order_by(OrgKnowledgeDoc.id.asc())
    ).all()
    db.close()

    assert refreshed is not None
    assert refreshed.extraction_status == "complete"
    assert refreshed.raw_transcript
    assert any(doc.extraction_type == "raw_chunk" for doc in docs)
    assert any(doc.extraction_type == "objection" for doc in docs)
    assert any(doc.extraction_type == "pricing" for doc in docs)
