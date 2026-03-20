from __future__ import annotations

from types import SimpleNamespace

from app.db.session import SessionLocal
from app.schemas.knowledge import RetrievedChunk
from app.services.document_retrieval_service import DocumentRetrievalService
from app.services.grading_service import GradingService
from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session, _turn


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


def test_grading_prompt_includes_universal_knowledge_when_org_has_no_docs(seed_org, monkeypatch):
    def fake_retrieve_for_topic(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        del db, context_hint, k, min_score
        assert org_id == seed_org["org_id"]
        return [
            RetrievedChunk(
                chunk_id=f"universal-{topic[:12]}",
                document_id="universal-playbook",
                document_name="pest_control_d2d_universal_knowledge.md",
                text="Use neighbor framing, validate objections, and re-close after the answer.",
                similarity_score=0.93,
                is_universal=True,
            )
        ]

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fake_retrieve_for_topic)

    service = GradingService()
    db = SessionLocal()
    try:
        prompt_context = service._build_effective_prompt_template(
            db,
            session=SimpleNamespace(
                rep=SimpleNamespace(org_id=seed_org["org_id"]),
                scenario_id=seed_org["scenario_id"],
            ),
            prompt_template="unused",
            turns=[_turn("rep-1", stage="initial_pitch", text="We are already helping a few of your neighbors.")],
            session_context={"peak_resistance": 4},
        )
    finally:
        db.close()

    assert "=== Industry Sales Knowledge ===" in prompt_context
    assert "pest_control_d2d_universal_knowledge.md" in prompt_context
    assert "Weight company-specific technique guidance over generic best practices when they conflict." in prompt_context
