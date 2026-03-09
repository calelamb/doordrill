from __future__ import annotations

from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus
from app.schemas.knowledge import RetrievedChunk
from app.services.document_retrieval_service import DocumentRetrievalService
from app.services.provider_clients import MockLlmClient, MockSttClient, MockTtsClient, ProviderSuite
from app.voice import ws as voice_ws
from tests.test_ws_voice_pipeline import _create_assignment, _create_session, _run_turn


class CaptureMockLlmClient(MockLlmClient):
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80):
        self.system_prompts.append(system_prompt)
        async for chunk in super().stream_reply(
            rep_text=rep_text,
            stage=stage,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        ):
            yield chunk


def _seed_ready_document(seed_org: dict[str, str]) -> tuple[str, str]:
    db = SessionLocal()
    try:
        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Pricing FAQ",
            original_filename="pricing-faq.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/pricing-faq.txt",
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
            text="Monthly plans start at $89 and cover standard pest visits.",
            token_count=12,
            embedding=[0.8, 0.6, 0.0],
        )
        db.add(chunk)
        db.commit()
        return document.id, chunk.id
    finally:
        db.close()


def _retrieved_chunk(chunk_id: str, *, text: str, name: str = "Pricing FAQ", document_id: str = "doc-1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=name,
        text=text,
        similarity_score=0.92,
    )


def test_company_context_injected_into_prompt_when_documents_exist(client, seed_org, monkeypatch):
    _seed_ready_document(seed_org)
    llm = CaptureMockLlmClient()
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=llm, tts=MockTtsClient()),
    )
    monkeypatch.setattr(DocumentRetrievalService, "has_ready_documents", lambda self, db, *, org_id: True)
    monkeypatch.setattr(
        DocumentRetrievalService,
        "retrieve_for_topic",
        lambda self, db, *, org_id, topic, context_hint="", k=5, min_score=0.70: [
            _retrieved_chunk("chunk-a", text="I think I saw your monthly plan starts at $89."),
            _retrieved_chunk("chunk-b", text="Someone mentioned Terminix has a competitor discount.", document_id="doc-2", name="Competitor Notes"),
        ],
    )

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"
        rag_loaded = ws.receive_json()
        assert rag_loaded["type"] == "server.session.rag_context_loaded"
        _run_turn(ws, text="Hi, I'm with Acme Pest Control.", sequence=1)
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    assert llm.system_prompts
    assert any("LAYER 5 - WHAT YOU MAY KNOW ABOUT THIS COMPANY" in prompt for prompt in llm.system_prompts)
    assert any("WHAT YOU MAY KNOW" in prompt for prompt in llm.system_prompts)


def test_company_context_absent_when_no_documents(client, seed_org, monkeypatch):
    llm = CaptureMockLlmClient()
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=llm, tts=MockTtsClient()),
    )
    monkeypatch.setattr(DocumentRetrievalService, "has_ready_documents", lambda self, db, *, org_id: False)

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"
        _run_turn(ws, text="Hi, I'm with Acme Pest Control.", sequence=1)
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    assert llm.system_prompts
    assert all("LAYER 5 - WHAT YOU MAY KNOW ABOUT THIS COMPANY" not in prompt for prompt in llm.system_prompts)


def test_rag_failure_does_not_abort_session(client, seed_org, monkeypatch):
    llm = CaptureMockLlmClient()
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=llm, tts=MockTtsClient()),
    )
    monkeypatch.setattr(DocumentRetrievalService, "has_ready_documents", lambda self, db, *, org_id: True)

    def fail_retrieve(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        raise Exception("retrieval failed")

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fail_retrieve)

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"
        messages = _run_turn(ws, text="Hi, I'm with Acme Pest Control.", sequence=1)
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    assert any(message["type"] == "server.turn.committed" for message in messages)
    assert llm.system_prompts
    assert all("LAYER 5 - WHAT YOU MAY KNOW ABOUT THIS COMPANY" not in prompt for prompt in llm.system_prompts)


def test_rag_context_loaded_event_emitted_when_chunks_found(client, seed_org, monkeypatch):
    llm = CaptureMockLlmClient()
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=llm, tts=MockTtsClient()),
    )
    monkeypatch.setattr(DocumentRetrievalService, "has_ready_documents", lambda self, db, *, org_id: True)

    def fake_retrieve(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        if "pricing monthly plan" in topic:
            return [
                _retrieved_chunk("chunk-a", text="I think I saw your monthly plan starts at $89."),
                _retrieved_chunk("chunk-b", text="Your standard service includes exterior treatment.", document_id="doc-2", name="Service Sheet"),
            ]
        return [
            _retrieved_chunk("chunk-c", text="Someone mentioned your reviews are better than Terminix.", document_id="doc-3", name="Reviews"),
        ]

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fake_retrieve)

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"
        rag_loaded = ws.receive_json()
        assert rag_loaded["type"] == "server.session.rag_context_loaded"
        assert rag_loaded["payload"]["chunks_loaded"] == 3
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})
