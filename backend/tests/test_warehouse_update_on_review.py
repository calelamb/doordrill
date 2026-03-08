from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.user import User
from app.models.warehouse import FactRepDaily, FactSession
from app.models.types import ReviewReason
from app.services.manager_action_service import ManagerActionService
from app.services.manager_review_service import ManagerReviewService
from app.services.warehouse_etl_service import WarehouseEtlService
from tests.transcript_pipeline_helpers import seed_hostile_enrichment_session


def test_warehouse_fact_session_updates_after_manager_review(seed_org):
    seeded = seed_hostile_enrichment_session(seed_org)

    db = SessionLocal()
    try:
        warehouse = WarehouseEtlService()
        warehouse.write_session(db, seeded["session_id"])

        manager = db.get(User, seed_org["manager_id"])
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == seeded["session_id"]))
        session = db.scalar(select(DrillSession).where(DrillSession.id == seeded["session_id"]))
        fact_session = db.scalar(select(FactSession).where(FactSession.session_id == seeded["session_id"]))

        assert manager is not None
        assert scorecard is not None
        assert session is not None
        assert fact_session is not None
        assert fact_session.has_manager_review is False
        assert fact_session.override_score is None
        assert fact_session.override_delta is None

        ManagerActionService().submit_review(
            db,
            reviewer=manager,
            scorecard=scorecard,
            source_session=session,
            reason_code=ReviewReason.MANAGER_COACHING,
            override_score=7.8,
            notes="The close landed slightly better than the model scored it.",
        )
        db.commit()

        fact_session = db.scalar(select(FactSession).where(FactSession.session_id == seeded["session_id"]))
        assert fact_session is not None
        rep_daily = db.scalar(
            select(FactRepDaily).where(
                FactRepDaily.rep_id == seed_org["rep_id"],
                FactRepDaily.session_date == fact_session.session_date,
            )
        )

        assert fact_session.has_manager_review is True
        assert fact_session.override_score == 7.8
        assert fact_session.override_delta == 0.5
        assert rep_daily is not None
        assert rep_daily.override_count == 1
    finally:
        db.close()


def test_warehouse_fact_session_updates_after_coaching_note(seed_org):
    seeded = seed_hostile_enrichment_session(seed_org)

    db = SessionLocal()
    try:
        warehouse = WarehouseEtlService()
        warehouse.write_session(db, seeded["session_id"])

        manager = db.get(User, seed_org["manager_id"])
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == seeded["session_id"]))
        fact_session = db.scalar(select(FactSession).where(FactSession.session_id == seeded["session_id"]))

        assert manager is not None
        assert scorecard is not None
        assert fact_session is not None
        assert fact_session.has_coaching_note is False

        note = ManagerReviewService().create_coaching_note(
            db,
            scorecard_id=scorecard.id,
            reviewer=manager,
            note="Slow down before the close and confirm the objection is resolved first.",
            visible_to_rep=True,
            weakness_tags=["closing_technique"],
        )
        db.commit()

        fact_session = db.scalar(select(FactSession).where(FactSession.session_id == seeded["session_id"]))
        assert fact_session is not None
        rep_daily = db.scalar(
            select(FactRepDaily).where(
                FactRepDaily.rep_id == seed_org["rep_id"],
                FactRepDaily.session_date == fact_session.session_date,
            )
        )

        assert note is not None
        assert fact_session.has_coaching_note is True
        assert rep_daily is not None
        assert rep_daily.coaching_note_count == 1
    finally:
        db.close()
