import time
from types import SimpleNamespace

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.services.grading_service import GradingService


def _create_assignment(client, seed_org: dict[str, str]) -> dict:
    response = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "retry_policy": {"max_attempts": 2},
        },
    )
    assert response.status_code == 200
    return response.json()


def _run_session(client, seed_org: dict[str, str], assignment_id: str, transcript_hint: str) -> str:
    session = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert session.status_code == 200
    session_id = session.json()["id"]

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {"transcript_hint": transcript_hint, "codec": "opus"},
            }
        )
        for _ in range(80):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


def _await_scorecard_and_run(session_id: str) -> tuple[Scorecard, GradingRun]:
    scorecard = None
    grading_run = None
    for _ in range(40):
        db = SessionLocal()
        try:
            scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
            grading_run = db.scalar(
                select(GradingRun)
                .where(GradingRun.session_id == session_id)
                .order_by(GradingRun.created_at.desc())
            )
        finally:
            db.close()
        if scorecard is not None and grading_run is not None:
            break
        time.sleep(0.03)

    assert scorecard is not None
    assert grading_run is not None
    return scorecard, grading_run


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
    assert 0.0 <= grading_run.confidence_score <= 1.0
    opening = scorecard.category_scores["opening"]
    assert "confidence" in opening
    assert "rationale_summary" in opening
    assert "rationale_detail" in opening
    assert "behavioral_signals" in opening
    assert isinstance(opening["evidence_turn_ids"], list)


def test_prompt_version_is_loaded_from_active_record(client, seed_org):
    db = SessionLocal()
    try:
        for row in db.scalars(select(PromptVersion).where(PromptVersion.prompt_type == "grading_v2")).all():
            row.active = False
        prompt = PromptVersion(
            prompt_type="grading_v2",
            version="1.1.0",
            content="Return valid JSON only. Use the grading v2 schema exactly.",
            active=True,
        )
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        prompt_id = prompt.id
    finally:
        db.close()

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can improve coverage, handle price concerns, and book a better plan today.",
    )

    _, grading_run = _await_scorecard_and_run(session_id)
    assert grading_run.prompt_version_id == prompt_id


def test_confidence_computation_increases_with_more_evidence():
    service = GradingService()

    def turn(turn_id: str, *, stage: str, text: str, objection_tags: list[str] | None = None):
        return SimpleNamespace(
            id=turn_id,
            stage=stage,
            text=text,
            objection_tags=objection_tags or [],
            speaker=SimpleNamespace(value="rep"),
        )

    low_session = SimpleNamespace(
        turns=[
            turn("t1", stage="opening", text="Hi there"),
            turn("t2", stage="pitch", text="We do pest control"),
        ]
    )
    high_session = SimpleNamespace(
        turns=[
            turn("t1", stage="opening", text="Hi there"),
            turn("t2", stage="pitch", text="We lower your rate with better coverage"),
            turn("t3", stage="objection_handling", text="I hear the price concern", objection_tags=["price"]),
            turn("t4", stage="objection_handling", text="That is exactly why we lock the rate", objection_tags=["price"]),
            turn("t5", stage="close_attempt", text="If that works, we can schedule today"),
            turn("t6", stage="close_attempt", text="The next step is getting the first service booked"),
        ]
    )
    grading = {
        "evidence_turn_ids": ["t1", "t2", "t3", "t4", "t5"],
        "category_scores": {
            "opening": {"score": 7.2},
            "pitch_delivery": {"score": 7.0},
            "objection_handling": {"score": 7.6},
            "closing_technique": {"score": 7.1},
            "professionalism": {"score": 7.5},
        },
    }
    low_grading = {
        "evidence_turn_ids": ["t1"],
        "category_scores": {
            "opening": {"score": 6.5},
            "pitch_delivery": {"score": 6.0},
            "objection_handling": {"score": 0.0},
        },
    }

    low_confidence = service.compute_confidence(low_session, low_grading)
    high_confidence = service.compute_confidence(high_session, grading)

    assert 0.0 <= low_confidence <= 1.0
    assert 0.0 <= high_confidence <= 1.0
    assert high_confidence > low_confidence


def test_disagreement_alert_emitted_on_high_delta(client, seed_org):
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
