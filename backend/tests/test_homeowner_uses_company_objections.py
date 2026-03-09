from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.scenario import Scenario
from app.services.conversation_orchestrator import ConversationOrchestrator
from app.services.document_retrieval_service import DocumentRetrievalService


def test_homeowner_prompt_does_not_use_company_objections(seed_org, monkeypatch):
    def fake_retrieve_for_topic(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        raise AssertionError("homeowner prompt should not retrieve company training context")

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

    assert "Respond in 1-3 short sentences only." in prompt
    assert "Never write more than 2-3 sentences per response." in prompt
    assert "=== Company Training Material ===" not in prompt
    assert "Territory & Objection Context" not in prompt
