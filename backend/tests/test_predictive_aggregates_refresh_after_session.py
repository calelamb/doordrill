from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.postprocess_run import PostprocessRun
from app.models.scorecard import Scorecard
from app.services.session_postprocess_service import SessionPostprocessService
from tests.transcript_pipeline_helpers import create_assignment_and_session


def _build_scorecard(session_id: str) -> Scorecard:
    return Scorecard(
        session_id=session_id,
        overall_score=8.0,
        category_scores={},
        highlights=[],
        ai_summary="graded",
        evidence_turn_ids=[],
        weakness_tags=[],
    )


@pytest.mark.asyncio
async def test_refresh_runs_after_write_session(seed_org, monkeypatch):
    _, session_id = create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        service = SessionPostprocessService()
        calls: list[tuple[str, str]] = []

        async def fake_grade(inner_db, session_id: str):
            scorecard = _build_scorecard(session_id)
            inner_db.add(scorecard)
            inner_db.commit()
            inner_db.refresh(scorecard)
            return scorecard

        def fake_enrich(inner_db, session_id: str):
            return {"turn_count": 0, "fact_event_count": 0}

        def fake_write_recommendation_outcome(inner_db, *, session_id: str):
            return None

        def fake_write_session(inner_db, current_session_id: str):
            calls.append(("write_session", current_session_id))
            return {"session_id": current_session_id, "fact_session_id": "fact-session-1"}

        def fake_refresh_predictive_aggregates(inner_db, *, org_id: str | None = None):
            calls.append(("refresh_predictive_aggregates", org_id or ""))
            return {"scenario_outcome_aggregate_rows": 3, "rep_cohort_benchmark_rows": 2}

        monkeypatch.setattr(service.grading_service, "grade_session", fake_grade)
        monkeypatch.setattr(service.turn_enrichment_service, "enrich_session", fake_enrich)
        monkeypatch.setattr(
            service.adaptive_training_service,
            "write_recommendation_outcome",
            fake_write_recommendation_outcome,
        )
        monkeypatch.setattr(service.warehouse_etl_service, "write_session", fake_write_session)
        monkeypatch.setattr(
            service.warehouse_etl_service,
            "refresh_predictive_aggregates",
            fake_refresh_predictive_aggregates,
        )

        result = await service.run_task_inline(db, session_id=session_id, task_type="grade")

        assert result["status"] == "completed"
        assert calls == [
            ("write_session", session_id),
            ("refresh_predictive_aggregates", seed_org["org_id"]),
        ]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_refresh_failure_does_not_fail_postprocess(seed_org, monkeypatch):
    _, session_id = create_assignment_and_session(seed_org)
    db = SessionLocal()
    try:
        service = SessionPostprocessService()

        async def fake_grade(inner_db, session_id: str):
            scorecard = _build_scorecard(session_id)
            inner_db.add(scorecard)
            inner_db.commit()
            inner_db.refresh(scorecard)
            return scorecard

        def fake_enrich(inner_db, session_id: str):
            return {"turn_count": 0, "fact_event_count": 0}

        def fake_write_recommendation_outcome(inner_db, *, session_id: str):
            return None

        def fake_write_session(inner_db, current_session_id: str):
            return {"session_id": current_session_id, "fact_session_id": "fact-session-1"}

        def fake_refresh_predictive_aggregates(inner_db, *, org_id: str | None = None):
            raise RuntimeError(f"refresh failed for {org_id}")

        monkeypatch.setattr(service.grading_service, "grade_session", fake_grade)
        monkeypatch.setattr(service.turn_enrichment_service, "enrich_session", fake_enrich)
        monkeypatch.setattr(
            service.adaptive_training_service,
            "write_recommendation_outcome",
            fake_write_recommendation_outcome,
        )
        monkeypatch.setattr(service.warehouse_etl_service, "write_session", fake_write_session)
        monkeypatch.setattr(
            service.warehouse_etl_service,
            "refresh_predictive_aggregates",
            fake_refresh_predictive_aggregates,
        )

        result = await service.run_task_inline(db, session_id=session_id, task_type="grade")

        assert result["status"] == "completed"
        run_row = db.scalar(
            select(PostprocessRun).where(PostprocessRun.session_id == session_id, PostprocessRun.task_type == "grade")
        )
        assert run_row is not None
        assert run_row.status == "completed"
    finally:
        db.close()
