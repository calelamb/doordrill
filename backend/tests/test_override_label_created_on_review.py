from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.training import OverrideLabel
from app.models.types import AssignmentStatus, ReviewReason, SessionStatus
from app.models.user import User
from app.services.manager_action_service import ManagerActionService


def _ensure_prompt_version(db) -> PromptVersion:
    prompt_version = db.scalar(
        select(PromptVersion).where(
            PromptVersion.prompt_type == "grading_v2",
            PromptVersion.version == "1.0.0",
        )
    )
    if prompt_version is not None:
        return prompt_version

    prompt_version = PromptVersion(
        prompt_type="grading_v2",
        version="1.0.0",
        content="test prompt",
        active=True,
    )
    db.add(prompt_version)
    db.commit()
    db.refresh(prompt_version)
    return prompt_version


def _seed_reviewable_scorecard(
    db,
    *,
    seed_org: dict[str, str],
    overall_score: float,
    started_at: datetime,
) -> tuple[DrillSession, Scorecard, GradingRun]:
    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "override_label_test"},
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
        overall_score=overall_score,
        scorecard_schema_version="v2",
        category_scores={
            "opening": {"score": overall_score},
            "pitch_delivery": {"score": overall_score},
            "objection_handling": {"score": overall_score},
            "closing_technique": {"score": overall_score},
            "professionalism": {"score": overall_score},
        },
        highlights=[],
        ai_summary="Test scorecard",
        evidence_turn_ids=[],
        weakness_tags=["closing_technique"],
    )
    db.add(scorecard)
    db.commit()
    db.refresh(scorecard)

    prompt_version = _ensure_prompt_version(db)
    grading_run = GradingRun(
        session_id=session.id,
        scorecard_id=scorecard.id,
        prompt_version_id=prompt_version.id,
        model_name="gpt-test",
        model_latency_ms=100,
        input_token_count=300,
        output_token_count=150,
        status="success",
        raw_llm_response="{}",
        parse_error=None,
        overall_score=overall_score,
        confidence_score=0.7,
        started_at=started_at + timedelta(minutes=4),
        completed_at=started_at + timedelta(minutes=4, seconds=3),
    )
    db.add(grading_run)
    db.commit()
    db.refresh(grading_run)
    return session, scorecard, grading_run


def _seed_prior_reviews(
    db,
    *,
    seed_org: dict[str, str],
    reviewer: User,
    count: int,
) -> None:
    service = ManagerActionService()
    base_started_at = datetime.now(timezone.utc) - timedelta(days=2)
    for index in range(count):
        session, scorecard, _ = _seed_reviewable_scorecard(
            db,
            seed_org=seed_org,
            overall_score=6.0,
            started_at=base_started_at + timedelta(minutes=index),
        )
        service.submit_review(
            db,
            reviewer=reviewer,
            scorecard=scorecard,
            source_session=session,
            reason_code=ReviewReason.REVIEW_ONLY,
            override_score=None,
            notes="Prior calibration review.",
        )
        db.commit()


def _submit_override_review(
    *,
    seed_org: dict[str, str],
    prior_review_count: int,
    ai_score: float,
    override_score: float,
) -> OverrideLabel:
    db = SessionLocal()
    try:
        reviewer = db.get(User, seed_org["manager_id"])
        assert reviewer is not None

        if prior_review_count:
            _seed_prior_reviews(db, seed_org=seed_org, reviewer=reviewer, count=prior_review_count)

        session, scorecard, grading_run = _seed_reviewable_scorecard(
            db,
            seed_org=seed_org,
            overall_score=ai_score,
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        review = ManagerActionService().submit_review(
            db,
            reviewer=reviewer,
            scorecard=scorecard,
            source_session=session,
            reason_code=ReviewReason.MANAGER_COACHING,
            override_score=override_score,
            notes="Manager corrected the overall score.",
        )
        db.commit()
        db.refresh(review)

        label = db.scalar(select(OverrideLabel).where(OverrideLabel.review_id == review.id))
        assert label is not None
        assert label.grading_run_id == grading_run.id
        assert label.ai_overall_score == ai_score
        assert label.override_overall_score == override_score
        return label
    finally:
        db.close()


def test_override_label_created_on_low_delta_review(seed_org):
    label = _submit_override_review(
        seed_org=seed_org,
        prior_review_count=0,
        ai_score=6.1,
        override_score=6.6,
    )

    assert label.label_quality == "low"
    assert label.override_delta_overall == 0.5
    assert label.is_high_disagreement is False


def test_override_label_created_on_medium_delta_review(seed_org):
    label = _submit_override_review(
        seed_org=seed_org,
        prior_review_count=2,
        ai_score=6.0,
        override_score=7.4,
    )

    assert label.label_quality == "medium"
    assert label.override_delta_overall == 1.4
    assert label.is_high_disagreement is False


def test_override_label_created_on_high_quality_review(seed_org):
    label = _submit_override_review(
        seed_org=seed_org,
        prior_review_count=9,
        ai_score=6.2,
        override_score=8.7,
    )

    assert label.label_quality == "high"
    assert label.override_delta_overall == 2.5
    assert label.is_high_disagreement is True
