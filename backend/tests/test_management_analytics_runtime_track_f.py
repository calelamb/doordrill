import time

from sqlalchemy import select

from app.api.manager import management_analytics_service
from app.db.session import SessionLocal
from app.models.analytics import AnalyticsFactSession, AnalyticsMaterializedView
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


def test_management_analytics_cache_and_operations(client, seed_org):
    management_analytics_service.cache.clear()

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can improve coverage and lower the monthly cost if we get you started today.",
    )

    scorecard = None
    fact_session = None
    for _ in range(30):
        db = SessionLocal()
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        fact_session = db.get(AnalyticsFactSession, session_id)
        db.close()
        if scorecard is not None and fact_session is not None:
            break
        time.sleep(0.03)

    assert scorecard is not None
    assert fact_session is not None

    headers = {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}
    first = client.get(
        "/manager/command-center",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=headers,
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["_meta"]["cache_status"] == "miss"
    assert first_body["_meta"]["analytics_last_refresh_at"] is not None

    second = client.get(
        "/manager/command-center",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=headers,
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["_meta"]["cache_status"] == "hit"
    assert second_body["_projection"]["view_name"] == "command_center"

    team = client.get(
        "/manager/analytics",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=headers,
    )
    assert team.status_code == 200
    assert team.json()["_meta"]["query_name"] == "team_analytics"

    ops = client.get(
        "/manager/analytics/operations",
        params={"manager_id": seed_org["manager_id"]},
        headers=headers,
    )
    assert ops.status_code == 200
    ops_body = ops.json()
    assert ops_body["cache"]["backend"] in {"memory", "redis"}
    assert "refresh_runs" in ops_body
    assert "warehouse" in ops_body
    assert ops_body["materialized_views"]["count"] >= 1
    assert ops_body["partitions"]["count"] >= 1

    db = SessionLocal()
    try:
        assert db.scalar(
            select(AnalyticsMaterializedView.id).where(
                AnalyticsMaterializedView.manager_id == seed_org["manager_id"],
                AnalyticsMaterializedView.view_name == "command_center",
                AnalyticsMaterializedView.period_key == "30",
            )
        ) is not None
    finally:
        db.close()

    coaching = client.post(
        f"/manager/scorecards/{scorecard.id}/coaching-notes",
        json={
            "note": "Slow down after the opener and ask the homeowner one confirming question.",
            "visible_to_rep": True,
            "weakness_tags": ["pace", "opening"],
        },
        headers=headers,
    )
    assert coaching.status_code == 200

    refreshed = client.get(
        "/manager/command-center",
        params={"manager_id": seed_org["manager_id"], "period": "30"},
        headers=headers,
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["_meta"]["cache_status"] == "miss"
