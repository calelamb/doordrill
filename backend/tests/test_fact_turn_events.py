from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.transcript import FactTurnEvent
from app.services.turn_enrichment_service import TurnEnrichmentService
from tests.transcript_pipeline_helpers import seed_hostile_enrichment_session, seed_interested_enrichment_session


def test_fact_turn_events_cover_hostile_timeline(seed_org):
    seeded = seed_hostile_enrichment_session(seed_org)
    db = SessionLocal()
    try:
        service = TurnEnrichmentService()
        result = service.enrich_session(db, seeded["session_id"])
        rerun = service.enrich_session(db, seeded["session_id"])

        fact_rows = db.scalars(
            select(FactTurnEvent).where(FactTurnEvent.session_id == seeded["session_id"]).order_by(FactTurnEvent.occurred_at.asc())
        ).all()
        fact_types = {row.event_type for row in fact_rows}

        assert result["fact_event_count"] == rerun["fact_event_count"] == len(fact_rows)
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


def test_fact_turn_events_cover_interested_stage_stall(seed_org):
    seeded = seed_interested_enrichment_session(seed_org)
    db = SessionLocal()
    try:
        service = TurnEnrichmentService()
        result = service.enrich_session(db, seeded["session_id"])

        fact_rows = db.scalars(
            select(FactTurnEvent).where(FactTurnEvent.session_id == seeded["session_id"]).order_by(FactTurnEvent.occurred_at.asc())
        ).all()
        fact_types = {row.event_type for row in fact_rows}

        assert result["fact_event_count"] == len(fact_rows)
        assert {
            "emotion_transition",
            "objection_resolved",
            "stage_stall",
            "resistance_drop",
            "high_realism_turn",
            "session_ended_interested",
        }.issubset(fact_types)

        stage_stall = next(row for row in fact_rows if row.event_type == "stage_stall")
        assert stage_stall.turn_id == seeded["rep_turn_id"]
        assert stage_stall.stage_before == stage_stall.stage_after == "objection_handling"

        ended = next(row for row in fact_rows if row.event_type == "session_ended_interested")
        assert ended.turn_id is None
        assert ended.emotion_after == "interested"
    finally:
        db.close()
