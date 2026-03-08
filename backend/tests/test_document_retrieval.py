from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus, UserRole
from app.models.user import Organization, User
from app.services.document_retrieval_service import DocumentRetrievalService


def test_document_retrieval_ranks_closest_chunk_and_enforces_org_isolation(client, seed_org, monkeypatch):
    query_vector = [0.8, 0.6, 0.0]
    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", lambda self, query: query_vector)

    db = SessionLocal()
    primary = OrgDocument(
        org_id=seed_org["org_id"],
        name="Primary Playbook",
        original_filename="playbook.txt",
        file_type=OrgDocumentFileType.TXT,
        storage_key="org-documents/acme/primary.txt",
        status=OrgDocumentStatus.READY,
        chunk_count=3,
        token_count=120,
        uploaded_by=seed_org["manager_id"],
    )
    secondary = OrgDocument(
        org_id=seed_org["org_id"],
        name="Closer Notes",
        original_filename="closer.txt",
        file_type=OrgDocumentFileType.TXT,
        storage_key="org-documents/acme/closer.txt",
        status=OrgDocumentStatus.READY,
        chunk_count=1,
        token_count=40,
        uploaded_by=seed_org["manager_id"],
    )
    db.add_all([primary, secondary])
    db.flush()

    chunk_1 = OrgDocumentChunk(
        document_id=primary.id,
        org_id=seed_org["org_id"],
        chunk_index=0,
        text="Lead with value first.",
        token_count=5,
        embedding=[1.0, 0.0, 0.0],
    )
    chunk_2 = OrgDocumentChunk(
        document_id=primary.id,
        org_id=seed_org["org_id"],
        chunk_index=1,
        text="Handle price objections by isolating the concern and restating value.",
        token_count=12,
        embedding=[0.8, 0.6, 0.0],
    )
    chunk_3 = OrgDocumentChunk(
        document_id=secondary.id,
        org_id=seed_org["org_id"],
        chunk_index=0,
        text="Ask for the next step clearly.",
        token_count=7,
        embedding=[0.0, 1.0, 0.0],
    )
    db.add_all([chunk_1, chunk_2, chunk_3])

    other_org = Organization(name="Other Org Retrieval", industry="solar", plan_tier="pro")
    db.add(other_org)
    db.flush()
    other_manager = User(
        org_id=other_org.id,
        role=UserRole.MANAGER,
        name="Other Manager",
        email="other-manager-retrieval@example.com",
    )
    db.add(other_manager)
    db.flush()
    other_document = OrgDocument(
        org_id=other_org.id,
        name="Other Org Playbook",
        original_filename="other.txt",
        file_type=OrgDocumentFileType.TXT,
        storage_key="org-documents/other/other.txt",
        status=OrgDocumentStatus.READY,
        chunk_count=1,
        token_count=20,
        uploaded_by=other_manager.id,
    )
    db.add(other_document)
    db.flush()
    db.add(
        OrgDocumentChunk(
            document_id=other_document.id,
            org_id=other_org.id,
            chunk_index=0,
            text="This should never be returned for the primary org.",
            token_count=10,
            embedding=[0.8, 0.6, 0.0],
        )
    )
    db.commit()

    service = DocumentRetrievalService()
    chunks = service.retrieve(
        db,
        org_id=seed_org["org_id"],
        query="What does our playbook say about price objections?",
        k=3,
        min_score=0.7,
    )
    assert len(chunks) == 2
    assert chunks[0].chunk_id == chunk_2.id
    assert chunks[0].document_id == primary.id
    assert chunks[0].document_name == "Primary Playbook"
    assert chunks[0].similarity_score > 0.7
    assert all(item.document_id != other_document.id for item in chunks)

    formatted = service.format_for_prompt(chunks, max_tokens=40)
    assert formatted.startswith("=== Company Training Material ===")
    assert "[From: Primary Playbook]" in formatted
    assert "Other Org Playbook" not in formatted

    db.close()

    response = client.post(
        "/manager/documents/query",
        json={
            "manager_id": seed_org["manager_id"],
            "query": "What does our playbook say about price objections?",
            "k": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["has_documents"] is True
    assert body["chunks"][0]["chunk_id"] == chunk_2.id
    assert all(item["document_id"] != other_document.id for item in body["chunks"])


