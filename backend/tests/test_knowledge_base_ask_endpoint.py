from __future__ import annotations

from app.api import manager as manager_api
from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus
from app.services.document_retrieval_service import DocumentRetrievalService


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def test_knowledge_base_ask_endpoint_returns_grounded_answer_and_sources(client, seed_org, monkeypatch):
    monkeypatch.setattr(DocumentRetrievalService, "_embed_query", lambda self, query: [0.0, 1.0, 0.0])

    db = SessionLocal()
    try:
        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Retention Script",
            original_filename="retention.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/acme/retention.txt",
            status=OrgDocumentStatus.READY,
            chunk_count=2,
            token_count=54,
            uploaded_by=seed_org["manager_id"],
        )
        db.add(document)
        db.flush()

        chunk = OrgDocumentChunk(
            document_id=document.id,
            org_id=seed_org["org_id"],
            chunk_index=0,
            text="When a homeowner says they already have pest control, confirm that coverage matters, ask what they wish were better, and show the gaps before comparing price.",
            token_count=25,
            embedding=[0.0, 1.0, 0.0],
        )
        db.add(chunk)
        db.commit()
    finally:
        db.close()

    def fake_claude(*, system_prompt: str, user_prompt: str, max_tokens: int, model: str | None = None):
        assert "Answer the manager's question using only the provided company training material." in user_prompt
        assert "Retention Script" in user_prompt
        assert "show the gaps before comparing price" in user_prompt
        return {
            "answer": "The script says to confirm coverage matters, ask what they wish were better, and show service gaps before comparing price."
        }

    monkeypatch.setattr(manager_api.manager_ai_service, "_call_claude_json", fake_claude)

    response = client.post(
        "/manager/documents/ask",
        headers=_manager_headers(seed_org),
        json={
            "manager_id": seed_org["manager_id"],
            "question": "How should I answer when the homeowner says they already have pest control?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "show service gaps before comparing price" in body["answer"]
    assert len(body["sources"]) == 1
    assert body["sources"][0]["document_name"] == "Retention Script"
    assert "already have pest control" in body["sources"][0]["text"]
