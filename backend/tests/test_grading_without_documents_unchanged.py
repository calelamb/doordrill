from __future__ import annotations

from app.services.document_retrieval_service import DocumentRetrievalService
from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session


def test_grading_without_documents_unchanged(client, seed_org, monkeypatch):
    def fake_retrieve_for_topic(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        assert org_id == seed_org["org_id"]
        return []

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fake_retrieve_for_topic)

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can explain the value clearly and ask for the next step before we wrap up.",
    )

    scorecard, grading_run = _await_scorecard_and_run(session_id)

    assert scorecard is not None
    assert grading_run.status == "fallback_used"
    assert grading_run.raw_llm_response is not None
    assert "=== Company Training Material ===" not in grading_run.raw_llm_response
    assert "Weight company-specific technique guidance over generic" not in grading_run.raw_llm_response
