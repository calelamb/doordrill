import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.scorecard import Scorecard


def _create_assignment(client, seed_org: dict[str, str], *, due_at: str | None = None) -> dict:
    payload = {
        "scenario_id": seed_org["scenario_id"],
        "rep_id": seed_org["rep_id"],
        "assigned_by": seed_org["manager_id"],
        "retry_policy": {"max_attempts": 2},
    }
    if due_at is not None:
        payload["due_at"] = due_at
    response = client.post("/manager/assignments", json=payload)
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


def _await_scorecard(session_id: str, *, timeout_seconds: float = 60) -> Scorecard:
    scorecard = None
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        finally:
            db.close()
        if scorecard is not None:
            break
        time.sleep(0.1)

    assert scorecard is not None, f"scorecard was not created for session {session_id} within {timeout_seconds} seconds"
    return scorecard


def test_management_intelligence_endpoints(client, seed_org):
    first_assignment = _create_assignment(client, seed_org)
    first_session_id = _run_session(
        client,
        seed_org,
        first_assignment["id"],
        "Hi, I can lower your price today and schedule now.",
    )
    first_scorecard = _await_scorecard(first_session_id)

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

    override = client.patch(
        f"/manager/scorecards/{first_scorecard.id}",
        json={
            "reviewer_id": seed_org["manager_id"],
            "reason_code": "manager_coaching",
            "override_score": 7.2,
            "notes": "Adjusted for a better close than the base model credited.",
        },
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert override.status_code == 200

    second_assignment = _create_assignment(client, seed_org)
    second_session_id = _run_session(
        client,
        seed_org,
        second_assignment["id"],
        "I know you already have service, but I can improve coverage and lock a better monthly rate.",
    )
    _await_scorecard(second_session_id)

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

    team_alias = client.get(
        "/manager/analytics/team",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert team_alias.status_code == 200
    assert "summary" in team_alias.json()

    rep_alias = client.get(
        f"/manager/analytics/reps/{seed_org['rep_id']}",
        params={"manager_id": seed_org["manager_id"], "days": 30},
        headers=manager_headers,
    )
    assert rep_alias.status_code == 200
    assert rep_alias.json()["rep_id"] == seed_org["rep_id"]

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
    if "_projection" in coaching_body:
        assert coaching_body["_projection"]["view_name"] == "coaching_analytics"
    assert coaching_body["summary"]["coaching_note_count"] >= 1
    assert "manager_calibration" in coaching_body
    assert "recent_notes" in coaching_body
    assert coaching_body["retry_impact"]
    assert coaching_body["intervention_segments"]
    assert "calibration_drift_timeline" in coaching_body
    assert "score_drift_by_scenario" in coaching_body
    assert "focus_turn_id" in coaching_body["recent_notes"][0]

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
    assert "focus_turn_id" in explorer_body["items"][0]

    _create_assignment(
        client,
        seed_org,
        due_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )

    alerts = client.get(
        "/manager/alerts",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert alerts.status_code == 200
    alerts_body = alerts.json()
    if "_projection" in alerts_body:
        assert alerts_body["_projection"]["view_name"] == "alerts"
    assert "items" in alerts_body
    overdue_alert = next((item for item in alerts_body["items"] if item["kind"] == "overdue_assignments"), None)
    assert overdue_alert is not None

    ack = client.post(
        f"/manager/alerts/{overdue_alert['id']}/ack",
        params={"manager_id": seed_org["manager_id"]},
        headers=manager_headers,
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"

    alerts_after_ack = client.get(
        "/manager/alerts",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert alerts_after_ack.status_code == 200
    assert overdue_alert["id"] not in {item["id"] for item in alerts_after_ack.json()["items"]}

    command_center_after_ack = client.get(
        "/manager/command-center",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert command_center_after_ack.status_code == 200
    assert overdue_alert["id"] not in {item["id"] for item in command_center_after_ack.json()["alerts_preview"]}

    benchmarks = client.get(
        "/manager/benchmarks",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=manager_headers,
    )
    assert benchmarks.status_code == 200
    assert "score_benchmarks" in benchmarks.json()

    metric_definitions = client.get(
        "/manager/analytics/metrics/definitions",
        params={"manager_id": seed_org["manager_id"]},
        headers=manager_headers,
    )
    assert metric_definitions.status_code == 200
    assert metric_definitions.json()["items"]

    actions = client.get(
        "/manager/actions",
        params={"manager_id": seed_org["manager_id"], "limit": 50},
        headers=manager_headers,
    )
    assert actions.status_code == 200
    assert any(item["action_type"] == "alert.acknowledged" for item in actions.json()["items"])
