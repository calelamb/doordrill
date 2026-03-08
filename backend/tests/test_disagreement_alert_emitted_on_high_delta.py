from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.analytics import AnalyticsFactAlert
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.training import OverrideLabel
from app.models.types import AssignmentStatus, ReviewReason, SessionStatus
from app.models.user import User
from app.services.manager_action_service import ManagerActionService
from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session


def _seed_direct_reviewable_scorecard(seed_org: dict[str, str]) -> dict[str, str]:
    db = SessionLocal()
    try:
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "grading_disagreement_test"},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
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
            overall_score=6.1,
            scorecard_schema_version="v2",
            category_scores={
                "opening": {
                    "score": 6.0,
                    "confidence": 0.6,
                    "rationale_summary": "Average opener",
                    "rationale_detail": "The opener worked but did not create strong momentum.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": [],
                    "improvement_target": "Lead with relevance",
                },
                "pitch_delivery": {
                    "score": 6.1,
                    "confidence": 0.62,
                    "rationale_summary": "Average pitch",
                    "rationale_detail": "The value explanation was serviceable but not sharp.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": [],
                    "improvement_target": "Use sharper specifics",
                },
                "objection_handling": {
                    "score": 6.3,
                    "confidence": 0.67,
                    "rationale_summary": "Partial objection handling",
                    "rationale_detail": "The rep addressed the concern but did not fully land the reframing.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": ["acknowledges_concern"],
                    "improvement_target": "Confirm agreement",
                },
                "closing_technique": {
                    "score": 5.8,
                    "confidence": 0.58,
                    "rationale_summary": "Weak close",
                    "rationale_detail": "The rep did not secure a firm next step.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": [],
                    "improvement_target": "Ask directly for next step",
                },
                "professionalism": {
                    "score": 6.3,
                    "confidence": 0.66,
                    "rationale_summary": "Professional enough",
                    "rationale_detail": "The tone stayed calm and respectful.",
                    "evidence_turn_ids": [],
                    "behavioral_signals": [],
                    "improvement_target": None,
                },
            },
            highlights=[
                {"type": "strong", "note": "You stayed composed.", "turn_id": None},
                {"type": "improve", "note": "Push for a firmer close.", "turn_id": None},
            ],
            ai_summary="You handled the conversation reasonably well but left too much ambiguity in the close.",
            evidence_turn_ids=[],
            weakness_tags=["closing_technique"],
        )
        db.add(scorecard)

        prompt_version = PromptVersion(
            prompt_type="grading_v2",
            version="1.0.0",
            content="test prompt",
            active=True,
        )
        db.add(prompt_version)
        db.commit()
        db.refresh(scorecard)
        db.refresh(prompt_version)

        grading_run = GradingRun(
            session_id=session.id,
            scorecard_id=scorecard.id,
            prompt_version_id=prompt_version.id,
            model_name="gpt-test",
            model_latency_ms=90,
            input_token_count=300,
            output_token_count=180,
            status="success",
            raw_llm_response="{}",
            parse_error=None,
            overall_score=6.1,
            confidence_score=0.71,
            started_at=started_at + timedelta(minutes=4),
            completed_at=started_at + timedelta(minutes=4, seconds=3),
        )
        db.add(grading_run)
        db.commit()
        db.refresh(grading_run)
        return {"session_id": session.id, "scorecard_id": scorecard.id, "grading_run_id": grading_run.id}
    finally:
        db.close()


def test_disagreement_alert_emitted_on_high_delta(seed_org):
    seeded = _seed_direct_reviewable_scorecard(seed_org)
    db = SessionLocal()
    try:
        manager = db.get(User, seed_org["manager_id"])
        scorecard = db.scalar(select(Scorecard).where(Scorecard.id == seeded["scorecard_id"]))
        session = db.scalar(select(DrillSession).where(DrillSession.id == seeded["session_id"]))
        assert manager is not None
        assert scorecard is not None
        assert session is not None

        review = ManagerActionService().submit_review(
            db,
            reviewer=manager,
            scorecard=scorecard,
            source_session=session,
            reason_code=ReviewReason.MANAGER_COACHING,
            override_score=9.5,
            notes="The model under-credited the session materially.",
        )
        db.commit()
        db.refresh(review)

        alerts = db.scalars(
            select(AnalyticsFactAlert)
            .where(
                AnalyticsFactAlert.manager_id == seed_org["manager_id"],
                AnalyticsFactAlert.session_id == seeded["session_id"],
                AnalyticsFactAlert.kind == "grading_disagreement",
            )
            .order_by(AnalyticsFactAlert.occurred_at.desc())
        ).all()
        assert alerts
        assert alerts[0].metadata_json["scorecard_id"] == seeded["scorecard_id"]
        assert alerts[0].metadata_json["reviewer_id"] == seed_org["manager_id"]
        assert alerts[0].metadata_json["prompt_version_id"]
        assert alerts[0].metadata_json["session_id"] == seeded["session_id"]
        assert alerts[0].metadata_json["ai_score"] == 6.1
        assert alerts[0].metadata_json["override_score"] == 9.5
        assert alerts[0].metadata_json["delta"] >= 2.0

        label = db.scalar(select(OverrideLabel).where(OverrideLabel.review_id == review.id))
        assert label is not None
    finally:
        db.close()


def test_calibration_endpoint_returns_recent_disagreements(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "Hi, I can lower your price today, handle the price objection, and schedule service now.",
    )
    scorecard, grading_run = _await_scorecard_and_run(session_id)

    override = client.patch(
        f"/manager/scorecards/{scorecard.id}",
        json={
            "reviewer_id": seed_org["manager_id"],
            "reason_code": "manager_coaching",
            "override_score": 9.5,
            "notes": "The rep earned much more credit than the model gave.",
        },
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert override.status_code == 200

    calibration = client.get(
        "/manager/analytics/calibration",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert calibration.status_code == 200
    body = calibration.json()
    matching = next(item for item in body["items"] if item["session_id"] == session_id)
    assert matching["delta"] >= 2.0
    assert matching["prompt_version_id"] == grading_run.prompt_version_id
