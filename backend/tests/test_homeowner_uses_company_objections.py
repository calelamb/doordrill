from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.scenario import Scenario
from app.schemas.knowledge import RetrievedChunk
from app.services.conversation_orchestrator import ConversationOrchestrator
from app.services.document_retrieval_service import DocumentRetrievalService


def test_homeowner_uses_company_objections(seed_org, monkeypatch):
    def fake_retrieve_for_topic(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        assert org_id == seed_org["org_id"]
        assert topic == "homeowner objections territory D2D door to door sales typical concerns"
        assert "skeptical homeowner" in context_hint
        assert "pest_control" in context_hint
        assert "price" in context_hint
        assert "trust" in context_hint
        return [
            RetrievedChunk(
                chunk_id="chunk-homeowner-1",
                document_id="document-homeowner-1",
                document_name="Territory Objection Playbook",
                text="Homeowners in this territory usually push on monthly cost and ask whether local proof exists.",
                similarity_score=0.91,
            )
        ]

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fake_retrieve_for_topic)

    db = SessionLocal()
    try:
        scenario = db.scalar(select(Scenario).where(Scenario.id == seed_org["scenario_id"]))
        assert scenario is not None

        orchestrator = ConversationOrchestrator()
        orchestrator.bind_session_context(
            "session-homeowner-context",
            scenario,
            prompt_version="conversation_v1",
            db=db,
            org_id=seed_org["org_id"],
            rep_id=seed_org["rep_id"],
        )
        prompt = orchestrator._build_system_prompt(
            stage_after="door_knock",
            session_id="session-homeowner-context",
        )
    finally:
        db.close()

    assert "=== Territory & Objection Context (from your company's training materials) ===" in prompt
    assert "=== Company Training Material ===" in prompt
    assert "Territory Objection Playbook" in prompt
    assert "monthly cost" in prompt
    assert "more realistic and representative" in prompt
