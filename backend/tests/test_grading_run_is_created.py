from __future__ import annotations

from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session


def test_grading_run_is_created_with_v2_scorecard(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "Hi, I can lower your monthly rate today and get the service scheduled now.",
    )

    scorecard, grading_run = _await_scorecard_and_run(session_id)

    assert scorecard.scorecard_schema_version == "v2"
    assert grading_run.scorecard_id == scorecard.id
    assert grading_run.prompt_version_id is not None
    assert grading_run.model_name
    assert grading_run.status
