from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.prompt_version import PromptVersion
from app.services.grading_service import GradingService
from app.services.prompt_experiment_service import PromptExperimentService


def test_prompt_routing_is_deterministic(seed_org):
    db = SessionLocal()
    try:
        control = PromptVersion(
            prompt_type="grading_v2",
            version="control",
            content="control prompt",
            active=True,
        )
        challenger = PromptVersion(
            prompt_type="grading_v2",
            version="challenger",
            content="challenger prompt",
            active=False,
        )
        db.add_all([control, challenger])
        db.commit()
        db.refresh(control)
        db.refresh(challenger)

        PromptExperimentService().create_experiment(
            db,
            prompt_type="grading_v2",
            control_version_id=control.id,
            challenger_version_id=challenger.id,
            challenger_traffic_pct=50,
            min_sessions_for_decision=2,
        )
        db.commit()

        service = GradingService()
        session_id = "session-deterministic-route"
        first = service._select_prompt_version(db, session_id=session_id)
        second = service._select_prompt_version(db, session_id=session_id)

        assert first.id == second.id

        routed_ids = {
            service._select_prompt_version(db, session_id=f"session-{index}").id
            for index in range(200)
        }
        assert control.id in routed_ids
        assert challenger.id in routed_ids

        same_again = {
            f"session-{index}": service._select_prompt_version(db, session_id=f"session-{index}").id
            for index in range(20)
        }
        repeated = {
            f"session-{index}": service._select_prompt_version(db, session_id=f"session-{index}").id
            for index in range(20)
        }
        assert same_again == repeated
    finally:
        db.close()
