from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.warehouse import DimRep, DimScenario, DimTime, FactRepDaily, FactSession
from app.services.turn_enrichment_service import TurnEnrichmentService
from app.services.warehouse_etl_service import WarehouseEtlService
from tests.transcript_pipeline_helpers import seed_hostile_enrichment_session


def test_warehouse_write_session_is_idempotent(seed_org):
    seeded = seed_hostile_enrichment_session(seed_org)

    db = SessionLocal()
    try:
        session = db.scalar(select(DrillSession).where(DrillSession.id == seeded["session_id"]))
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == seeded["session_id"]))
        prompt_version = PromptVersion(
            prompt_type="grading_v2",
            version="1.0.0",
            content="test prompt",
            active=True,
        )
        db.add(prompt_version)
        db.commit()
        db.refresh(prompt_version)

        assert session is not None
        assert scorecard is not None

        TurnEnrichmentService().enrich_session(db, seeded["session_id"])

        grading_run = GradingRun(
            session_id=seeded["session_id"],
            scorecard_id=scorecard.id,
            prompt_version_id=prompt_version.id,
            model_name="gpt-test",
            model_latency_ms=110,
            input_token_count=420,
            output_token_count=260,
            status="success",
            raw_llm_response="{}",
            parse_error=None,
            overall_score=scorecard.overall_score,
            confidence_score=0.74,
            started_at=session.started_at + timedelta(minutes=5),
            completed_at=session.started_at + timedelta(minutes=5, seconds=4),
        )
        db.add(grading_run)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        service = WarehouseEtlService()
        first = service.write_session(db, seeded["session_id"])
        second = service.write_session(db, seeded["session_id"])

        fact_rows = db.scalars(select(FactSession).where(FactSession.session_id == seeded["session_id"])).all()
        rep_daily_rows = db.scalars(select(FactRepDaily).where(FactRepDaily.rep_id == seed_org["rep_id"])).all()

        assert first["session_id"] == second["session_id"] == seeded["session_id"]
        assert len(fact_rows) == 1
        assert len(rep_daily_rows) == 1

        fact_row = fact_rows[0]
        assert fact_row.rep_id == seed_org["rep_id"]
        assert fact_row.manager_id == seed_org["manager_id"]
        assert fact_row.scenario_id == seed_org["scenario_id"]
        assert fact_row.overall_score == scorecard.overall_score
        assert fact_row.prompt_version_id == grading_run.prompt_version_id
        assert fact_row.grading_confidence == grading_run.confidence_score
        assert fact_row.turn_count == 4
        assert fact_row.rep_turn_count == 2
        assert fact_row.ai_turn_count == 2
        assert fact_row.objection_count == 2
        assert fact_row.barge_in_count == 2
        assert fact_row.final_emotion == "hostile"
        assert fact_row.weakness_tag_1 == "objection_handling"
        assert fact_row.weakness_tag_2 == "closing_technique"

        rep_daily = rep_daily_rows[0]
        assert rep_daily.session_count == 1
        assert rep_daily.scored_count == 1
        assert rep_daily.avg_score == scorecard.overall_score
        assert rep_daily.avg_objection_handling == 6.1
        assert rep_daily.avg_closing_technique == 5.4

        assert db.get(DimRep, seed_org["rep_id"]) is not None
        assert db.get(DimScenario, seed_org["scenario_id"]) is not None
        assert db.get(DimTime, fact_row.session_date) is not None
        assert db.scalar(select(func.count(FactSession.fact_session_id)).where(FactSession.session_id == seeded["session_id"])) == 1
    finally:
        db.close()
