from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus, UserRole
from app.models.universal_knowledge import UniversalKnowledgeChunk
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
    non_universal_chunks = [item for item in chunks if not item.is_universal]
    assert len(non_universal_chunks) == 2
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


def test_retrieve_for_topic_uses_in_process_ttl_cache(seed_org, monkeypatch):
    query_calls = {"count": 0}

    def fake_embed(self, query):
        query_calls["count"] += 1
        return [0.8, 0.6, 0.0]

    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", fake_embed)

    db = SessionLocal()
    try:
        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Pricing Cache Notes",
            original_filename="pricing-cache.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/acme/pricing-cache.txt",
            status=OrgDocumentStatus.READY,
            chunk_count=1,
            token_count=50,
            uploaded_by=seed_org["manager_id"],
        )
        db.add(document)
        db.flush()
        db.add(
            OrgDocumentChunk(
                document_id=document.id,
                org_id=seed_org["org_id"],
                chunk_index=0,
                text="Monthly pricing coverage and service details for homeowners.",
                token_count=10,
                embedding=[0.8, 0.6, 0.0],
            )
        )
        db.commit()

        service = DocumentRetrievalService()
        first = service.retrieve_for_topic(
            db,
            org_id=seed_org["org_id"],
            topic="monthly pricing coverage",
            context_hint="Skeptical Homeowner",
            k=3,
            min_score=0.70,
        )
        second = service.retrieve_for_topic(
            db,
            org_id=seed_org["org_id"],
            topic="monthly pricing coverage",
            context_hint="Different Scenario Name",
            k=3,
            min_score=0.70,
        )

        assert first
        assert second
        assert query_calls["count"] == 1
        assert second[0].chunk_id == first[0].chunk_id
    finally:
        db.close()


def test_retrieve_returns_universal_chunks_when_org_has_no_uploaded_docs(seed_org, monkeypatch):
    query_vector = [1.0, 0.0, 0.0]
    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", lambda self, query: query_vector)

    db = SessionLocal()
    try:
        db.add_all(
            [
                UniversalKnowledgeChunk(
                    category="intro",
                    content="Use a relaxed first contact at the door and earn five more seconds of attention.",
                    source_tag="industry_standard",
                    is_active=True,
                    embedding=[1.0, 0.0, 0.0],
                ),
                UniversalKnowledgeChunk(
                    category="closing",
                    content="Use an option close with two times instead of asking a yes or no question.",
                    source_tag="industry_standard",
                    is_active=True,
                    embedding=[0.9, 0.1, 0.0],
                ),
            ]
        )
        db.commit()

        chunks = DocumentRetrievalService().retrieve(
            db,
            org_id=seed_org["org_id"],
            query="How should I open and close at the door?",
            k=2,
            min_score=0.70,
        )

        assert len(chunks) == 2
        assert all(chunk.is_universal for chunk in chunks)
        assert chunks[0].document_name == "Industry Knowledge [intro]"
    finally:
        db.close()


def test_retrieve_prioritizes_org_specific_chunks_before_universal(seed_org, monkeypatch):
    query_vector = [1.0, 0.0, 0.0]
    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", lambda self, query: query_vector)

    db = SessionLocal()
    try:
        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Closing Playbook",
            original_filename="closing-playbook.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/acme/closing-playbook.txt",
            status=OrgDocumentStatus.READY,
            chunk_count=1,
            token_count=30,
            uploaded_by=seed_org["manager_id"],
        )
        db.add(document)
        db.flush()
        db.add(
            OrgDocumentChunk(
                document_id=document.id,
                org_id=seed_org["org_id"],
                chunk_index=0,
                text="Handle the objection directly, then ask for the appointment without lingering.",
                token_count=12,
                embedding=[1.0, 0.0, 0.0],
            )
        )
        db.add(
            UniversalKnowledgeChunk(
                category="closing",
                content="Use an option close like Tuesday or Thursday once the homeowner is engaged.",
                source_tag="industry_standard",
                is_active=True,
                embedding=[0.95, 0.05, 0.0],
            )
        )
        db.commit()

        service = DocumentRetrievalService()
        chunks = service.retrieve(
            db,
            org_id=seed_org["org_id"],
            query="How should I close after handling the objection?",
            k=2,
            min_score=0.70,
        )

        assert len(chunks) == 2
        assert chunks[0].is_universal is False
        assert chunks[0].document_name == "Closing Playbook"
        assert chunks[1].is_universal is True
        assert chunks[1].document_name == "Industry Knowledge [closing]"

        formatted = service.format_for_prompt(chunks, max_tokens=200)
        assert "=== Company Training Material ===" in formatted
        assert "=== Industry Sales Knowledge ===" in formatted
        assert formatted.index("=== Company Training Material ===") < formatted.index("=== Industry Sales Knowledge ===")
    finally:
        db.close()


def test_retrieve_excludes_universal_chunks_below_min_score(seed_org, monkeypatch):
    query_vector = [1.0, 0.0, 0.0]
    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", lambda self, query: query_vector)

    db = SessionLocal()
    try:
        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Org Objection Notes",
            original_filename="objection-notes.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/acme/objection-notes.txt",
            status=OrgDocumentStatus.READY,
            chunk_count=1,
            token_count=30,
            uploaded_by=seed_org["manager_id"],
        )
        db.add(document)
        db.flush()
        db.add(
            OrgDocumentChunk(
                document_id=document.id,
                org_id=seed_org["org_id"],
                chunk_index=0,
                text="Ask a direct follow-up question to isolate whether the concern is price or timing.",
                token_count=13,
                embedding=[1.0, 0.0, 0.0],
            )
        )
        db.add(
            UniversalKnowledgeChunk(
                category="backyard_close",
                content="Walk the backyard and point out standing water or ant activity before resetting the close.",
                source_tag="industry_standard",
                is_active=True,
                embedding=[0.0, 1.0, 0.0],
            )
        )
        db.commit()

        chunks = DocumentRetrievalService().retrieve(
            db,
            org_id=seed_org["org_id"],
            query="How do I isolate the objection and move forward?",
            k=2,
            min_score=0.70,
        )

        assert len(chunks) == 1
        assert chunks[0].is_universal is False
        assert all(not chunk.is_universal for chunk in chunks)
    finally:
        db.close()
