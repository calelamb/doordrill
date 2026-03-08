from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.training import OverrideLabel, PromptExperiment
from app.models.types import AssignmentStatus, ReviewReason, SessionStatus


def _seed_override_label_for_prompt(
    db,
    *,
    seed_org: dict[str, str],
    prompt_version_id: str,
    ai_score: float,
    override_score: float,
    minute_offset: int,
) -> None:
    started_at = datetime.now(timezone.utc) - timedelta(minutes=minute_offset + 10)
    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "prompt_experiment_test"},
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    session = DrillSession(
        assignment_id=assignment.id,
        rep_id=seed_org["rep_id"],
        scenario_id=seed_org["scenario_id"],
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        duration_seconds=300,
        status=SessionStatus.GRADED,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    scorecard = Scorecard(
        session_id=session.id,
        overall_score=ai_score,
        scorecard_schema_version="v2",
        category_scores={"opening": {"score": ai_score}},
        highlights=[],
        ai_summary="test",
        evidence_turn_ids=[],
        weakness_tags=[],
    )
    db.add(scorecard)
    db.commit()
    db.refresh(scorecard)

    grading_run = GradingRun(
        session_id=session.id,
        scorecard_id=scorecard.id,
        prompt_version_id=prompt_version_id,
        model_name="gpt-test",
        model_latency_ms=100,
        input_token_count=300,
        output_token_count=150,
        status="success",
        raw_llm_response="{}",
        parse_error=None,
        overall_score=ai_score,
        confidence_score=0.7,
        started_at=started_at + timedelta(minutes=4),
        completed_at=started_at + timedelta(minutes=4, seconds=4),
    )
    db.add(grading_run)
    db.commit()
    db.refresh(grading_run)

    review = ManagerReview(
        scorecard_id=scorecard.id,
        reviewer_id=seed_org["manager_id"],
        reviewed_at=datetime.now(timezone.utc),
        reason_code=ReviewReason.MANAGER_COACHING,
        override_score=override_score,
        notes="manager correction",
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    delta = round(abs(override_score - ai_score), 2)
    db.add(
        OverrideLabel(
            review_id=review.id,
            grading_run_id=grading_run.id,
            session_id=session.id,
            manager_id=seed_org["manager_id"],
            org_id=seed_org["org_id"],
            ai_overall_score=ai_score,
            ai_category_scores=dict(scorecard.category_scores or {}),
            override_overall_score=override_score,
            override_category_scores=None,
            override_reason_text=review.notes,
            override_delta_overall=delta,
            is_high_disagreement=delta >= 2.0,
            label_quality="high" if delta >= 2.0 else "medium",
            exported_at=None,
            export_batch_id=None,
        )
    )
    db.commit()


def test_prompt_experiment_evaluation_and_promotion(client, seed_org):
    headers = {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}

    db = SessionLocal()
    try:
        control = db.scalar(
            select(PromptVersion).where(
                PromptVersion.prompt_type == "grading_v2",
                PromptVersion.version == "1.0.0",
            )
        )
        assert control is not None
        challenger = PromptVersion(
            prompt_type="grading_v2",
            version="1.1.0",
            content="challenger prompt",
            active=False,
        )
        db.add(challenger)
        db.commit()
        db.refresh(challenger)
        challenger_id = challenger.id
        control_id = control.id
    finally:
        db.close()

    create = client.post(
        "/admin/prompt-experiments",
        json={
            "prompt_type": "grading_v2",
            "control_version_id": control_id,
            "challenger_version_id": challenger_id,
            "challenger_traffic_pct": 25,
            "min_sessions_for_decision": 2,
        },
        headers=headers,
    )
    assert create.status_code == 200
    experiment_id = create.json()["id"]

    db = SessionLocal()
    try:
        _seed_override_label_for_prompt(db, seed_org=seed_org, prompt_version_id=control_id, ai_score=6.0, override_score=7.4, minute_offset=1)
        _seed_override_label_for_prompt(db, seed_org=seed_org, prompt_version_id=control_id, ai_score=6.1, override_score=7.3, minute_offset=2)
        _seed_override_label_for_prompt(db, seed_org=seed_org, prompt_version_id=challenger_id, ai_score=6.2, override_score=6.5, minute_offset=3)
        _seed_override_label_for_prompt(db, seed_org=seed_org, prompt_version_id=challenger_id, ai_score=6.3, override_score=6.4, minute_offset=4)
    finally:
        db.close()

    evaluate = client.post(
        f"/admin/prompt-experiments/{experiment_id}/evaluate",
        headers=headers,
    )
    assert evaluate.status_code == 200
    body = evaluate.json()
    assert body["control_session_count"] == 2
    assert body["challenger_session_count"] == 2
    assert body["control_mean_calibration_error"] > body["challenger_mean_calibration_error"]
    assert body["winner"] == "challenger"
    assert body["p_value"] == 0.01

    fetch = client.get(
        f"/admin/prompt-experiments/{experiment_id}",
        headers=headers,
    )
    assert fetch.status_code == 200
    assert fetch.json()["winner"] == "challenger"

    promote = client.post(
        f"/admin/prompt-experiments/{experiment_id}/promote",
        headers=headers,
    )
    assert promote.status_code == 200
    assert promote.json()["status"] == "completed"
    assert promote.json()["winner"] == "challenger"

    db = SessionLocal()
    try:
        experiment = db.get(PromptExperiment, experiment_id)
        control = db.get(PromptVersion, control_id)
        challenger = db.get(PromptVersion, challenger_id)
        assert experiment is not None
        assert experiment.status == "completed"
        assert experiment.ended_at is not None
        assert control is not None and control.active is False
        assert challenger is not None and challenger.active is True
    finally:
        db.close()
