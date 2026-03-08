from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.postprocess_run import PostprocessRun
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.transcript import FactTurnEvent
from app.models.types import AssignmentStatus, EventDirection, SessionStatus, TurnSpeaker
from app.services.session_postprocess_service import SessionPostprocessService
from app.services.turn_enrichment_service import TurnEnrichmentService


def _create_assignment_and_session(seed_org: dict[str, str]) -> tuple[str, str]:
    db = SessionLocal()
    try:
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "turn_enrichment_test"},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        started_at = datetime.now(timezone.utc) - timedelta(minutes=15)
        session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=seed_org["scenario_id"],
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=6),
            duration_seconds=360,
            status=SessionStatus.GRADED,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return assignment.id, session.id
    finally:
        db.close()


def _seed_enrichment_session(seed_org: dict[str, str]) -> dict[str, str]:
    _, session_id = _create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        assert session is not None

        base = session.started_at
        rep_turn_1 = SessionTurn(
            session_id=session.id,
            turn_index=1,
            speaker=TurnSpeaker.REP,
            stage="objection_handling",
            text="Totally fair. A lot of homeowners ask about price first because they want real value.",
            started_at=base + timedelta(minutes=1),
            ended_at=base + timedelta(minutes=1, seconds=12),
            objection_tags=["price"],
        )
        ai_turn_1 = SessionTurn(
            session_id=session.id,
            turn_index=2,
            speaker=TurnSpeaker.AI,
            stage="objection_handling",
            text="Okay, that makes sense. What actually makes your service different?",
            started_at=base + timedelta(minutes=1, seconds=13),
            ended_at=base + timedelta(minutes=1, seconds=28),
            objection_tags=[],
        )
        rep_turn_2 = SessionTurn(
            session_id=session.id,
            turn_index=3,
            speaker=TurnSpeaker.REP,
            stage="close_attempt",
            text="If we can get this started today, would you want to lock it in now?",
            started_at=base + timedelta(minutes=3),
            ended_at=base + timedelta(minutes=3, seconds=8),
            objection_tags=["timing"],
        )
        ai_turn_2 = SessionTurn(
            session_id=session.id,
            turn_index=4,
            speaker=TurnSpeaker.AI,
            stage="close_attempt",
            text="Wait, hold on. I'm not ready to do that right now.",
            started_at=base + timedelta(minutes=3, seconds=9),
            ended_at=base + timedelta(minutes=3, seconds=22),
            objection_tags=[],
        )
        db.add_all([rep_turn_1, ai_turn_1, rep_turn_2, ai_turn_2])
        db.commit()
        for turn in (rep_turn_1, ai_turn_1, rep_turn_2, ai_turn_2):
            db.refresh(turn)

        db.add_all(
            [
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-connected",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=1,
                    event_ts=base,
                    payload={
                        "state": "connected",
                        "stage": "door_knock",
                        "emotion": "skeptical",
                        "resistance_level": 3,
                        "objection_pressure": 3,
                        "active_objections": ["price"],
                        "queued_objections": ["trust"],
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-homeowner-1",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=2,
                    event_ts=base + timedelta(minutes=1, seconds=12),
                    payload={
                        "state": "homeowner_state_updated",
                        "stage": "objection_handling",
                        "emotion": "curious",
                        "resistance_level": 2,
                        "objection_pressure": 1,
                        "active_objections": [],
                        "queued_objections": ["trust"],
                        "emotion_before": "skeptical",
                        "emotion_after": "curious",
                        "behavioral_signals": ["acknowledges_concern", "explains_value"],
                        "objection_tags": ["price"],
                        "resolved_objections_this_turn": ["price"],
                        "objection_pressure_before": 3,
                        "objection_pressure_after": 1,
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-commit-1",
                    event_type="server.turn.committed",
                    direction=EventDirection.SERVER,
                    sequence=3,
                    event_ts=base + timedelta(minutes=1, seconds=29),
                    payload={
                        "rep_turn_id": rep_turn_1.id,
                        "ai_turn_id": ai_turn_1.id,
                        "stage": "objection_handling",
                        "emotion_before": "skeptical",
                        "emotion_after": "curious",
                        "behavioral_signals": ["acknowledges_concern", "explains_value"],
                        "objection_tags": ["price"],
                        "interrupted": False,
                        "micro_behavior": {
                            "tone": "warming",
                            "sentence_length": "long",
                            "behaviors": ["tone_shift"],
                            "interruption_type": None,
                            "pause_profile": {"opening_pause_ms": 180, "total_pause_ms": 420},
                            "realism_score": 8.4,
                        },
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-homeowner-2",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=4,
                    event_ts=base + timedelta(minutes=3, seconds=8),
                    payload={
                        "state": "homeowner_state_updated",
                        "stage": "close_attempt",
                        "transition": {"from": "objection_handling", "to": "close_attempt"},
                        "emotion": "hostile",
                        "resistance_level": 5,
                        "objection_pressure": 4,
                        "active_objections": ["timing"],
                        "queued_objections": ["trust", "decision_authority"],
                        "emotion_before": "curious",
                        "emotion_after": "hostile",
                        "behavioral_signals": ["pushes_close", "ignores_objection"],
                        "objection_tags": ["timing"],
                        "resolved_objections_this_turn": [],
                        "objection_pressure_before": 1,
                        "objection_pressure_after": 4,
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-barge-in",
                    event_type="server.session.state",
                    direction=EventDirection.SERVER,
                    sequence=5,
                    event_ts=base + timedelta(minutes=3, seconds=12),
                    payload={
                        "state": "barge_in_detected",
                        "stage": "close_attempt",
                        "emotion": "hostile",
                        "resistance_level": 5,
                        "objection_pressure": 4,
                        "active_objections": ["timing"],
                        "queued_objections": ["trust", "decision_authority"],
                        "reason": "vad_speaking",
                        "barge_in_count": 1,
                    },
                ),
                SessionEvent(
                    session_id=session.id,
                    event_id="tx-commit-2",
                    event_type="server.turn.committed",
                    direction=EventDirection.SERVER,
                    sequence=6,
                    event_ts=base + timedelta(minutes=3, seconds=23),
                    payload={
                        "rep_turn_id": rep_turn_2.id,
                        "ai_turn_id": ai_turn_2.id,
                        "stage": "close_attempt",
                        "emotion_before": "curious",
                        "emotion_after": "hostile",
                        "behavioral_signals": ["pushes_close", "ignores_objection"],
                        "objection_tags": ["timing"],
                        "interrupted": True,
                        "interruption": {"reason": "vad_speaking", "barge_in_count": 1},
                        "micro_behavior": {
                            "tone": "confrontational",
                            "sentence_length": "short",
                            "behaviors": ["interruption"],
                            "interruption_type": "homeowner_cuts_off_rep",
                            "pause_profile": {"opening_pause_ms": 40, "total_pause_ms": 120},
                            "realism_score": 2.7,
                        },
                    },
                ),
                Scorecard(
                    session_id=session.id,
                    overall_score=7.3,
                    category_scores={
                        "opening": {"score": 8.2, "evidence_turn_ids": [rep_turn_1.id]},
                        "pitch_delivery": {"score": 7.6, "evidence_turn_ids": [rep_turn_1.id]},
                        "objection_handling": {"score": 6.1, "evidence_turn_ids": [rep_turn_2.id]},
                        "closing_technique": {"score": 5.4, "evidence_turn_ids": [rep_turn_2.id]},
                        "professionalism": {"score": 7.1, "evidence_turn_ids": [rep_turn_1.id, rep_turn_2.id]},
                    },
                    highlights=[{"type": "improve", "note": "Handle timing before trying to close.", "turn_id": rep_turn_2.id}],
                    ai_summary="Useful rep energy, but the close came too early after objection pressure rose.",
                    evidence_turn_ids=[rep_turn_1.id, rep_turn_2.id],
                    weakness_tags=["objection_handling", "closing_technique"],
                ),
            ]
        )
        db.commit()
        return {
            "session_id": session.id,
            "rep_turn_1_id": rep_turn_1.id,
            "ai_turn_1_id": ai_turn_1.id,
            "rep_turn_2_id": rep_turn_2.id,
            "ai_turn_2_id": ai_turn_2.id,
        }
    finally:
        db.close()


def test_turn_enrichment_populates_emotion_columns(seed_org):
    seeded = _seed_enrichment_session(seed_org)
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


def test_turn_enrichment_writes_fact_events_idempotently(seed_org):
    seeded = _seed_enrichment_session(seed_org)
    db = SessionLocal()
    try:
        service = TurnEnrichmentService()
        first_run = service.enrich_session(db, seeded["session_id"])
        second_run = service.enrich_session(db, seeded["session_id"])

        fact_rows = db.scalars(
            select(FactTurnEvent).where(FactTurnEvent.session_id == seeded["session_id"]).order_by(FactTurnEvent.occurred_at.asc())
        ).all()
        fact_types = {row.event_type for row in fact_rows}

        assert first_run["fact_event_count"] == second_run["fact_event_count"] == len(fact_rows)
        assert {
            "emotion_transition",
            "objection_resolved",
            "stage_advance",
            "resistance_drop",
            "high_realism_turn",
            "objection_surfaced",
            "resistance_spike",
            "barge_in",
            "low_realism_turn",
            "session_ended_hostile",
        }.issubset(fact_types)

        barge_in = next(row for row in fact_rows if row.event_type == "barge_in")
        assert barge_in.turn_id == seeded["ai_turn_2_id"]
        assert barge_in.context_json["reason"] == "vad_speaking"

        surfaced = next(row for row in fact_rows if row.event_type == "objection_surfaced")
        assert surfaced.objection_tag == "timing"
        assert surfaced.pressure_delta == 3
    finally:
        db.close()


@pytest.mark.asyncio
async def test_grade_postprocess_runs_turn_enrichment(seed_org, monkeypatch):
    _, session_id = _create_assignment_and_session(seed_org)
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
