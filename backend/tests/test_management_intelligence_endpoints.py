import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.scorecard import Scorecard


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
        for _ in range(60):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


def test_management_intelligence_endpoints(client, seed_org):
    first_assignment = _create_assignment(client, seed_org)
    first_session_id = _run_session(
        client,
        seed_org,
        first_assignment["id"],
        "Hi, I can lower your price today and schedule now.",
    )

    first_scorecard = None
    for _ in range(20):
        db = SessionLocal()
        first_scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == first_session_id))
        db.close()
        if first_scorecard is not None:
            break
        time.sleep(0.02)
    assert first_scorecard is not None

    coaching = client.post(
        f"/manager/scorecards/{first_scorecard.id}/coaching-notes",
        json={
            "note": "Slow down after the first objection and restate the value clearly.",
            "visible_to_rep": True,
            "weakness_tags": ["pace", "objection_handling"],
        },
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert coaching.status_code == 200

    second_assignment = _create_assignment(client, seed_org)
    _run_session(
        client,
        seed_org,
        second_assignment["id"],
        "I know you already have service, but I can improve coverage and lock a better monthly rate.",
    )

    manager_headers = {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}

    command_center = client.get(
        "/manager/command-center",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert command_center.status_code == 200
    command_center_body = command_center.json()
    assert "summary" in command_center_body
    assert "score_trend" in command_center_body
    assert "rep_risk_matrix" in command_center_body
    assert "scenario_pass_matrix" in command_center_body

    scenarios = client.get(
        "/manager/analytics/scenarios",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert scenarios.status_code == 200
    scenarios_body = scenarios.json()
    assert scenarios_body["items"]
    assert "difficulty_bands" in scenarios_body
    assert "objection_failure_map" in scenarios_body

    coaching_analytics = client.get(
        "/manager/analytics/coaching",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert coaching_analytics.status_code == 200
    coaching_body = coaching_analytics.json()
    assert coaching_body["summary"]["coaching_note_count"] >= 1
    assert "manager_calibration" in coaching_body
    assert "recent_notes" in coaching_body

    explorer = client.get(
        "/manager/analytics/explorer",
        params={"manager_id": seed_org["manager_id"], "period": "30", "reviewed": False},
        headers=manager_headers,
    )
    assert explorer.status_code == 200
    explorer_body = explorer.json()
    assert explorer_body["items"]
    assert "filters" in explorer_body
    assert "transcript_preview" in explorer_body["items"][0]

    alerts = client.get(
        "/manager/alerts",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert alerts.status_code == 200
    assert "items" in alerts.json()

    benchmarks = client.get(
        "/manager/benchmarks",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert benchmarks.status_code == 200
    assert "score_benchmarks" in benchmarks.json()
