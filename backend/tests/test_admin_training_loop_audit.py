from __future__ import annotations

import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.training import AdaptiveRecommendationOutcome
from app.schemas.knowledge import RetrievedChunk
from app.services.document_retrieval_service import DocumentRetrievalService
from tests.test_adaptive_training import _seed_adaptive_history
from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session
from tests.test_ws_voice_pipeline import _create_assignment as _create_assignment_id
from tests.test_ws_voice_pipeline import _create_session, _run_turn


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def _fetch_audit(client, seed_org: dict[str, str], session_id: str) -> dict:
    response = client.get(
        f"/admin/sessions/{session_id}/training-loop-audit",
        headers=_manager_headers(seed_org),
    )
    assert response.status_code == 200
    return response.json()


def _await_adaptive_outcome(assignment_id: str) -> AdaptiveRecommendationOutcome:
    outcome = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            outcome = db.scalar(
                select(AdaptiveRecommendationOutcome).where(
                    AdaptiveRecommendationOutcome.assignment_id == assignment_id
                )
            )
        finally:
            db.close()
        if outcome is not None and outcome.outcome_written_at is not None:
            return outcome
        time.sleep(0.1)
    raise AssertionError(f"adaptive outcome was not written for assignment {assignment_id} within 30 seconds")


def test_training_loop_audit_reports_company_context_when_available(client, seed_org, monkeypatch):
    monkeypatch.setattr(DocumentRetrievalService, "has_ready_documents", lambda self, db, *, org_id: True)

    def fake_retrieve(
        self,
        db,
        *,
        org_id: str,
        topic: str,
        context_hint: str = "",
        k: int = 5,
        min_score: float = 0.70,
    ) -> list[RetrievedChunk]:
        if "pricing monthly plan" in topic:
            return [
                RetrievedChunk(
                    chunk_id="pricing-1",
                    document_id="doc-pricing",
                    document_name="Pricing FAQ",
                    text="I think your monthly plan starts at $89.",
                    similarity_score=0.94,
                ),
                RetrievedChunk(
                    chunk_id="pricing-2",
                    document_id="doc-service",
                    document_name="Service Sheet",
                    text="The standard service includes exterior treatment.",
                    similarity_score=0.91,
                ),
            ]
        if "competitor comparison" in topic:
            return [
                RetrievedChunk(
                    chunk_id="competitor-1",
                    document_id="doc-competitor",
                    document_name="Competitor Notes",
                    text="Someone mentioned your reviews are stronger than Terminix.",
                    similarity_score=0.92,
                )
            ]
        if "grading methodology" in topic:
            return [
                RetrievedChunk(
                    chunk_id="grading-1",
                    document_id="doc-manual",
                    document_name="Company Objection Manual",
                    text="When price comes up, isolate the concern, restate monthly value, and close on the next step.",
                    similarity_score=0.95,
                )
            ]
        return []

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fake_retrieve)

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can lower your monthly rate, handle the price concern, and book the next step today.",
    )
    _await_scorecard_and_run(session_id)

    audit = _fetch_audit(client, seed_org, session_id)

    assert audit["finalization"]["scorecard_present"] is True
    assert audit["finalization"]["audio_artifact_count"] >= 1
    assert audit["finalization"]["postprocess_runs"]["grade"]["status"] == "completed"
    assert audit["prompt_audit"]["has_company_context"] is True
    assert audit["prompt_audit"]["company_doc_names"] == ["Pricing FAQ", "Service Sheet", "Competitor Notes"]
    assert audit["grading_audit"]["has_company_training_material"] is True
    assert audit["grading_audit"]["company_doc_names"] == ["Company Objection Manual"]


def test_training_loop_audit_reports_missing_company_context_when_no_docs_exist(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can lower your monthly rate, answer questions, and set the next step today.",
    )
    _await_scorecard_and_run(session_id)

    audit = _fetch_audit(client, seed_org, session_id)

    assert audit["prompt_audit"]["has_company_context"] is False
    assert audit["prompt_audit"]["company_doc_names"] == []
    assert audit["grading_audit"]["has_company_training_material"] is False
    assert audit["grading_audit"]["company_doc_names"] == []


def test_training_loop_audit_reports_adaptive_metadata_and_outcome(client, seed_org):
    _seed_adaptive_history(seed_org)

    assignment_response = client.post(
        f"/manager/reps/{seed_org['rep_id']}/adaptive-assignment",
        json={"assigned_by": seed_org["manager_id"], "retry_policy": {"max_attempts": 2}},
        headers=_manager_headers(seed_org),
    )
    assert assignment_response.status_code == 200
    assignment = assignment_response.json()["assignment"]

    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can lower your monthly cost, handle the objection, and set the next step today.",
        scenario_id=assignment["scenario_id"],
    )
    _await_scorecard_and_run(session_id)
    _await_adaptive_outcome(assignment["id"])

    audit = _fetch_audit(client, seed_org, session_id)

    assert audit["adaptive_audit"]["has_adaptive_metadata"] is True
    assert audit["adaptive_audit"]["focus_skills"]
    assert audit["adaptive_audit"]["baseline_skill_scores_present"] is True
    assert audit["adaptive_audit"]["outcome_present"] is True
    assert audit["adaptive_audit"]["skill_delta_present"] is True


def test_training_loop_audit_reports_prompt_continuity_and_behavior_directives(client, seed_org):
    assignment_id = _create_assignment_id(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"

        _run_turn(ws, text="Hi, I'm with Acme Pest Control.", sequence=1)
        _run_turn(ws, text="I understand price matters and I can show proof from local reviews.", sequence=2)
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    _await_scorecard_and_run(session_id)
    audit = _fetch_audit(client, seed_org, session_id)

    assert audit["prompt_audit"]["has_behavior_directives"] is True
    assert audit["prompt_audit"]["has_prior_turn_register"] is True
    assert audit["prompt_audit"]["prompt_token_count"] > 0
