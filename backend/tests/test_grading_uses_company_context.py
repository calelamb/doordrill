from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus
from app.schemas.knowledge import RetrievedChunk
from app.services.document_retrieval_service import DocumentRetrievalService
from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session


def test_grading_uses_company_context(client, seed_org, monkeypatch):
    db = SessionLocal()
    document = OrgDocument(
        org_id=seed_org["org_id"],
        name="Company Objection Manual",
        original_filename="objections.txt",
        file_type=OrgDocumentFileType.TXT,
        storage_key="org-documents/company-objections.txt",
        status=OrgDocumentStatus.READY,
        chunk_count=1,
        token_count=20,
        uploaded_by=seed_org["manager_id"],
    )
    db.add(document)
    db.flush()
    chunk = OrgDocumentChunk(
        document_id=document.id,
        org_id=seed_org["org_id"],
        chunk_index=0,
        text="When price comes up, isolate the concern, restate monthly value, and close on the next step.",
        token_count=16,
        embedding=[0.8, 0.6, 0.0],
    )
    db.add(chunk)
    db.commit()
    db.close()

    def fake_retrieve_for_topic(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        row = db.scalar(select(OrgDocumentChunk).where(OrgDocumentChunk.id == chunk.id))
        document_row = db.scalar(select(OrgDocument).where(OrgDocument.id == document.id))
        assert row is not None
        assert document_row is not None
        assert org_id == seed_org["org_id"]
        if "grading methodology" not in topic:
            return []
        return [
            RetrievedChunk(
                chunk_id=row.id,
                document_id=document_row.id,
                document_name=document_row.name,
                text=row.text,
                similarity_score=0.93,
            )
        ]

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fake_retrieve_for_topic)

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can lower your monthly rate, handle the price concern, and book the next step today.",
    )

    _, grading_run = _await_scorecard_and_run(session_id)

    assert grading_run.raw_llm_response is not None
    assert "=== Company Training Material ===" in grading_run.raw_llm_response
    assert "Company Objection Manual" in grading_run.raw_llm_response
    assert "Weight company-specific technique guidance over generic" in grading_run.raw_llm_response
