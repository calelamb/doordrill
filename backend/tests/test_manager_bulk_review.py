from app.db.session import SessionLocal
from app.models.types import UserRole
from app.models.user import Organization, User


def _create_assignment(client, seed_org: dict[str, str]) -> dict:
    response = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "min_score_target": 7.5,
            "retry_policy": {"max_attempts": 2},
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
                    "transcript_hint": "I can lower your pest service price and schedule a fast follow-up.",
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


def test_bulk_review_is_idempotent_and_skips_already_reviewed(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    response = client.post(
        "/manager/sessions/bulk-review",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
        json={
            "session_ids": [session_id],
            "idempotency_key": "bulk-review-key-1",
            "notes": "Reviewed in batch.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 1
    assert body["items"][0]["status"] == "created"

    repeat = client.post(
        "/manager/sessions/bulk-review",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
        json={
            "session_ids": [session_id],
            "idempotency_key": "bulk-review-key-1",
            "notes": "Reviewed in batch.",
        },
    )
    assert repeat.status_code == 200
    repeat_body = repeat.json()
    assert repeat_body["created_count"] == 0
    assert repeat_body["items"][0]["status"] == "already_reviewed"


def test_bulk_review_enforces_manager_ownership(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    db = SessionLocal()
    other_org = Organization(name="Other Org", industry="pest_control", plan_tier="pro")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    other_manager = User(
        org_id=other_org.id,
        role=UserRole.MANAGER,
        name="Other Manager",
        email="other-manager@example.com",
    )
    db.add(other_manager)
    db.commit()
    db.refresh(other_manager)
    db.close()

    response = client.post(
        "/manager/sessions/bulk-review",
        headers={"x-user-id": other_manager.id, "x-user-role": "manager"},
        json={
            "session_ids": [session_id],
            "idempotency_key": "bulk-review-key-2",
            "notes": "Should not be allowed.",
        },
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "forbidden"
