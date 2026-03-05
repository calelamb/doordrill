import time

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.notification_delivery import NotificationDelivery
from app.models.postprocess_run import PostprocessRun


def _create_assignment(client, seed_org: dict[str, str]) -> dict:
    response = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "retry_policy": {"max_attempts": 1},
        },
    )
    assert response.status_code == 200
    return response.json()


def _run_session(client, seed_org: dict[str, str], assignment_id: str) -> str:
    session_resp = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {
                    "transcript_hint": "We can lower your monthly price and schedule service today.",
                    "codec": "opus",
                },
            }
        )
        for _ in range(60):
            msg = ws.receive_json()
            if msg["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


def test_rep_device_token_register_and_revoke(client, seed_org):
    headers = {"x-user-id": seed_org["rep_id"], "x-user-role": "rep"}
    register = client.post(
        "/rep/device-tokens",
        json={"platform": "ios", "token": "ExponentPushToken[abcdefghijklmnopqrstuv12345]"},
        headers=headers,
    )
    assert register.status_code == 200
    token_id = register.json()["id"]

    revoke = client.delete(f"/rep/device-tokens/{token_id}", headers=headers)
    assert revoke.status_code == 200
    assert revoke.json()["ok"] is True


def test_manager_notification_feed_and_postprocess_audit(client, seed_org):
    settings = get_settings()
    settings.manager_notification_email_enabled = True
    settings.manager_notification_push_enabled = False
    settings.use_celery = False

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    for _ in range(30):
        feed = client.get(
            "/manager/notifications",
            params={"manager_id": seed_org["manager_id"]},
            headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
        )
        assert feed.status_code == 200
        items = feed.json()["items"]
        if any(item["session_id"] == session_id for item in items):
            break
        time.sleep(0.02)

    assert any(item["session_id"] == session_id for item in items)

    db = SessionLocal()
    deliveries = db.scalars(select(NotificationDelivery).where(NotificationDelivery.session_id == session_id)).all()
    runs = db.scalars(select(PostprocessRun).where(PostprocessRun.session_id == session_id)).all()
    db.close()

    assert deliveries
    assert any(delivery.channel == "email" for delivery in deliveries)
    assert {row.task_type for row in runs} == {"cleanup", "grade", "notify"}
