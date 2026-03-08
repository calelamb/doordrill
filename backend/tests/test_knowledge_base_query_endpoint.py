from __future__ import annotations

from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus
from app.services.document_retrieval_service import DocumentRetrievalService


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def test_knowledge_base_query_endpoint_returns_best_matching_chunks(client, seed_org, monkeypatch):
    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", lambda self, query: [0.8, 0.6, 0.0])

    db = SessionLocal()
    try:
        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Objection Playbook",
            original_filename="objections.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/acme/objections.txt",
            status=OrgDocumentStatus.READY,
            chunk_count=3,
            token_count=78,
            uploaded_by=seed_org["manager_id"],
        )
        db.add(document)
        db.flush()

        chunk_1 = OrgDocumentChunk(
            document_id=document.id,
            org_id=seed_org["org_id"],
            chunk_index=0,
            text="Open by asking if the homeowner has two minutes.",
            token_count=10,
            embedding=[1.0, 0.0, 0.0],
        )
        chunk_2 = OrgDocumentChunk(
            document_id=document.id,
            org_id=seed_org["org_id"],
            chunk_index=1,
            text="For the already-have-service objection, acknowledge the provider, isolate what they dislike, and compare coverage gaps before offering a switch.",
            token_count=24,
            embedding=[0.8, 0.6, 0.0],
        )
        chunk_3 = OrgDocumentChunk(
            document_id=document.id,
            org_id=seed_org["org_id"],
            chunk_index=2,
            text="Always ask directly for the next step after value is clear.",
            token_count=12,
            embedding=[0.1, 0.9, 0.0],
        )
        db.add_all([chunk_1, chunk_2, chunk_3])
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/manager/documents/query",
        headers=_manager_headers(seed_org),
        json={
            "manager_id": seed_org["manager_id"],
            "query": "What does our playbook say when the homeowner says they already have service?",
            "k": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_documents"] is True
    assert len(body["chunks"]) >= 1
    assert body["chunks"][0]["text"].startswith("For the already-have-service objection")
    assert body["chunks"][0]["similarity_score"] >= 0.7
