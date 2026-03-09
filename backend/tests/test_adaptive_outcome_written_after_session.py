import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.training import AdaptiveRecommendationOutcome
from tests.test_adaptive_training import _seed_adaptive_history
from tests.test_grading_engine_v2 import _await_scorecard_and_run, _run_session


def test_adaptive_outcome_written_after_session(client, seed_org):
    _seed_adaptive_history(seed_org)

    assignment_response = client.post(
        f"/manager/reps/{seed_org['rep_id']}/adaptive-assignment",
        json={"assigned_by": seed_org["manager_id"], "retry_policy": {"max_attempts": 2}},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert assignment_response.status_code == 200
    assignment_body = assignment_response.json()
    assignment = assignment_body["assignment"]
    selected = assignment_body["selected_scenario"]

    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can lower your monthly cost, handle the objection, and set the next step today.",
        scenario_id=assignment["scenario_id"],
    )
    _await_scorecard_and_run(session_id)

    outcome = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            outcome = db.scalar(
                select(AdaptiveRecommendationOutcome).where(
                    AdaptiveRecommendationOutcome.assignment_id == assignment["id"]
                )
            )
        finally:
            db.close()
        if outcome is not None and outcome.outcome_written_at is not None:
            break
        time.sleep(0.1)

    assert outcome is not None, f"adaptive outcome was not written for assignment {assignment['id']} within 30 seconds"
    assert outcome.session_id == session_id
    assert outcome.recommended_scenario_id == assignment["scenario_id"]
    assert set(outcome.recommended_focus_skills).issuperset(set(selected["focus_skills"]))
    assert outcome.baseline_skill_scores
    assert outcome.outcome_skill_scores
    assert outcome.skill_delta is not None
    assert set(outcome.skill_delta.keys()).issubset(set(outcome.recommended_focus_skills))
    assert outcome.outcome_overall_score is not None
    assert outcome.outcome_written_at is not None
