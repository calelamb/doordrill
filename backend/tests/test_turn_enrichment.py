from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.postprocess_run import PostprocessRun
from app.models.scorecard import Scorecard
from app.models.session import SessionTurn
from app.services.session_postprocess_service import SessionPostprocessService
from app.services.turn_enrichment_service import TurnEnrichmentService
from tests.transcript_pipeline_helpers import create_assignment_and_session, seed_hostile_enrichment_session


def test_turn_enrichment_populates_emotion_columns(seed_org):
    seeded = seed_hostile_enrichment_session(seed_org)
    db = SessionLocal()
    try:
        service = TurnEnrichmentService()
        result = service.enrich_session(db, seeded["session_id"])

        turns = db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == seeded["session_id"]).order_by(SessionTurn.turn_index.asc())
        ).all()
        turn_by_id = {turn.id: turn for turn in turns}

        rep_turn_1 = turn_by_id[seeded["rep_turn_1_id"]]
        ai_turn_1 = turn_by_id[seeded["ai_turn_1_id"]]
        rep_turn_2 = turn_by_id[seeded["rep_turn_2_id"]]
        ai_turn_2 = turn_by_id[seeded["ai_turn_2_id"]]

        assert rep_turn_1.emotion_before == "skeptical"
        assert rep_turn_1.emotion_after == "curious"
        assert rep_turn_1.emotion_changed is True
        assert rep_turn_1.active_objections == []
        assert rep_turn_1.queued_objections == ["trust"]
        assert rep_turn_1.behavioral_signals == ["acknowledges_concern", "explains_value"]
        assert rep_turn_1.was_graded is True
        assert rep_turn_1.evidence_for_categories == ["opening", "pitch_delivery", "professionalism"]
        assert rep_turn_1.is_high_quality is False

        assert ai_turn_1.mb_realism_score == pytest.approx(8.4)
        assert ai_turn_1.mb_tone == "warming"
        assert ai_turn_1.mb_opening_pause_ms == 180
        assert ai_turn_1.mb_total_pause_ms == 420

        assert rep_turn_2.stage == "close_attempt"
        assert rep_turn_2.emotion_before == "curious"
        assert rep_turn_2.emotion_after == "hostile"
        assert rep_turn_2.resistance_level == 5
        assert rep_turn_2.objection_pressure == 4
        assert rep_turn_2.active_objections == ["timing"]
        assert rep_turn_2.queued_objections == ["trust", "decision_authority"]
        assert rep_turn_2.mb_interruption_type == "homeowner_cuts_off_rep"
        assert rep_turn_2.mb_realism_score == pytest.approx(2.7)
        assert rep_turn_2.evidence_for_categories == ["closing_technique", "objection_handling", "professionalism"]

        assert ai_turn_2.mb_interruption_type == "homeowner_cuts_off_rep"
        assert ai_turn_2.mb_sentence_length == "short"
        assert result["turn_count"] == 4
    finally:
        db.close()


@pytest.mark.asyncio
async def test_grade_postprocess_runs_turn_enrichment(seed_org, monkeypatch):
    _, session_id = create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        service = SessionPostprocessService()
        calls: list[tuple[str, str]] = []

        async def fake_grade(inner_db, session_id: str):
            calls.append(("grade", session_id))
            scorecard = Scorecard(
                session_id=session_id,
                overall_score=8.0,
                category_scores={},
                highlights=[],
                ai_summary="graded",
                evidence_turn_ids=[],
                weakness_tags=[],
            )
            inner_db.add(scorecard)
            inner_db.commit()
            inner_db.refresh(scorecard)
            return scorecard

        def fake_enrich(inner_db, session_id: str):
            calls.append(("enrich", session_id))
            return {"turn_count": 0, "fact_event_count": 0}

        monkeypatch.setattr(service.grading_service, "grade_session", fake_grade)
        monkeypatch.setattr(service.turn_enrichment_service, "enrich_session", fake_enrich)

        result = await service.run_task_inline(db, session_id=session_id, task_type="grade")

        assert result["status"] == "completed"
        assert result["turn_enrichment"] == {"turn_count": 0, "fact_event_count": 0}
        assert calls == [("grade", session_id), ("enrich", session_id)]

        run_row = db.scalar(
            select(PostprocessRun).where(PostprocessRun.session_id == session_id, PostprocessRun.task_type == "grade")
        )
        assert run_row is not None
        assert run_row.status == "completed"
    finally:
        db.close()


def test_objection_types_endpoint_returns_seeded_taxonomy(client, seed_org):
    response = client.get(
        "/scenarios/objection-types",
        params={"industry": "pest_control"},
        headers={
            "x-user-id": seed_org["manager_id"],
            "x-user-role": "manager",
        },
    )

    assert response.status_code == 200
    body = response.json()
    tags = {item["tag"] for item in body}

    assert "price" in tags
    assert "incumbent_provider" in tags
    assert "decision_authority" in tags
    assert all(item["industry"] in {None, "pest_control"} for item in body)
