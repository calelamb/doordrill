from __future__ import annotations

from time import perf_counter

from app.db.session import SessionLocal
from app.services.document_retrieval_service import DocumentRetrievalService


def test_retrieval_empty_org_returns_immediately_without_embedding(seed_org, monkeypatch):
    def fail_embed(self, query: str):
        raise AssertionError("query embedding should not run when org has no ready documents")

    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", fail_embed)

    db = SessionLocal()
    service = DocumentRetrievalService()
    started = perf_counter()
    chunks = service.retrieve(
        db,
        org_id=seed_org["org_id"],
        query="How do we handle objections?",
    )
    elapsed_ms = (perf_counter() - started) * 1000
    db.close()

    assert chunks == []
    assert elapsed_ms < 500
