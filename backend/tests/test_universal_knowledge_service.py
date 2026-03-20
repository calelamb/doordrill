from __future__ import annotations

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.universal_knowledge import UniversalKnowledgeChunk
from app.services.universal_knowledge_service import UNIVERSAL_CATEGORIES, UniversalKnowledgeService


class _StubProcessingService:
    def embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        return [[float(index + 1), 0.0, 0.0] for index, _ in enumerate(chunks)]


def test_parse_seed_document_returns_valid_chunks():
    service = UniversalKnowledgeService(processing_service=_StubProcessingService())

    chunks = service.parse_seed_document()

    assert len(chunks) >= 15
    assert all(chunk.category in UNIVERSAL_CATEGORIES for chunk in chunks)
    assert all(chunk.source_tag == "industry_standard" for chunk in chunks)


def test_seed_is_idempotent_without_force():
    db = SessionLocal()
    try:
        service = UniversalKnowledgeService(processing_service=_StubProcessingService())
        parsed = service.parse_seed_document()

        inserted = service.seed(db)
        second_inserted = service.seed(db)
        total_rows = db.scalar(select(func.count()).select_from(UniversalKnowledgeChunk))

        assert inserted == len(parsed)
        assert second_inserted == 0
        assert total_rows == len(parsed)
    finally:
        db.close()


def test_seed_force_replaces_existing_chunks():
    db = SessionLocal()
    try:
        service = UniversalKnowledgeService(processing_service=_StubProcessingService())
        expected_count = len(service.parse_seed_document())

        first_inserted = service.seed(db)
        db.add(
            UniversalKnowledgeChunk(
                category="intro",
                content="stale universal knowledge sentinel",
                source_tag="stale_sentinel",
                is_active=True,
                embedding=[9.0, 0.0, 0.0],
            )
        )
        db.commit()

        forced_inserted = service.seed(db, force=True)
        total_rows = db.scalar(select(func.count()).select_from(UniversalKnowledgeChunk))
        stale_rows = db.scalar(
            select(func.count())
            .select_from(UniversalKnowledgeChunk)
            .where(UniversalKnowledgeChunk.source_tag == "stale_sentinel")
        )

        assert first_inserted == expected_count
        assert forced_inserted == expected_count
        assert total_rows == expected_count
        assert stale_rows == 0
    finally:
        db.close()
