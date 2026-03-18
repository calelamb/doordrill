import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.session import SessionArtifact


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


def _await_session_ended(ws) -> None:
    for _ in range(80):
        message = ws.receive_json()
        if message["type"] == "server.session.state" and message["payload"].get("state") == "ended":
            return
    raise AssertionError("session did not emit ended state")


def _run_session(client, seed_org: dict[str, str], assignment_id: str) -> str:
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
                "payload": {"transcript_hint": "Hi, I can lower your price today and schedule now.", "codec": "opus"},
            }
        )
        for _ in range(60):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})
        _await_session_ended(ws)

    return session_id


def test_auth_register_login_refresh(client):
    register = client.post(
        "/auth/register",
        json={
            "email": "new-manager@example.com",
            "password": "SecretPass123",
            "name": "New Manager",
            "role": "manager",
            "org_name": "New Org",
        },
    )
    assert register.status_code == 200
    body = register.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["role"] == "manager"

    login = client.post(
        "/auth/login",
        json={"email": "new-manager@example.com", "password": "SecretPass123"},
    )
    assert login.status_code == 200
    login_body = login.json()
    assert login_body["access_token"]

    refresh = client.post("/auth/refresh", json={"refresh_token": login_body["refresh_token"]})
    assert refresh.status_code == 200
    assert refresh.json()["access_token"]


def test_scenarios_crud_and_listing(client, seed_org):
    create = client.post(
        "/scenarios",
        json={
            "name": "Late Evening Objection",
            "industry": "pest_control",
            "difficulty": 3,
            "description": "Homeowner says it is too late right now.",
            "persona": {"attitude": "busy"},
            "rubric": {"opening": 10},
            "stages": ["door_knock", "objection_handling"],
            "created_by_id": seed_org["manager_id"],
        },
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert create.status_code == 200
    scenario_id = create.json()["id"]

    get_resp = client.get(f"/scenarios/{scenario_id}", headers={"x-user-id": seed_org["rep_id"], "x-user-role": "rep"})
    assert get_resp.status_code == 200

    update = client.put(
        f"/scenarios/{scenario_id}",
        json={"difficulty": 4, "description": "Updated scenario"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert update.status_code == 200
    assert update.json()["difficulty"] == 4

    listing = client.get("/scenarios", headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"})
    assert listing.status_code == 200
    assert any(item["id"] == scenario_id for item in listing.json())


def test_manager_and_rep_endpoint_conformance(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    manager_headers = {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}
    rep_headers = {"x-user-id": seed_org["rep_id"], "x-user-role": "rep"}

    team = client.get("/manager/team", params={"manager_id": seed_org["manager_id"]}, headers=manager_headers)
    assert team.status_code == 200
    assert any(item["id"] == seed_org["rep_id"] for item in team.json()["items"])

    assignments = client.get("/manager/assignments", params={"manager_id": seed_org["manager_id"]}, headers=manager_headers)
    assert assignments.status_code == 200
    assert any(item["id"] == assignment["id"] for item in assignments.json()["items"])

    sessions = client.get("/manager/sessions", params={"manager_id": seed_org["manager_id"]}, headers=manager_headers)
    assert sessions.status_code == 200
    assert any(item["session_id"] == session_id for item in sessions.json()["items"])

    detail = client.get(f"/manager/sessions/{session_id}", headers=manager_headers)
    assert detail.status_code == 200
    assert detail.json()["session"]["id"] == session_id

    audio = client.get(f"/manager/sessions/{session_id}/audio", headers=manager_headers)
    assert audio.status_code == 200
    assert audio.json()["url"]

    rep_sessions = client.get("/rep/sessions", params={"rep_id": seed_org["rep_id"]}, headers=rep_headers)
    assert rep_sessions.status_code == 200
    assert any(item["session_id"] == session_id for item in rep_sessions.json()["items"])

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        rep_progress = client.get("/rep/progress", params={"rep_id": seed_org["rep_id"]}, headers=rep_headers)
        assert rep_progress.status_code == 200
        if rep_progress.json()["scored_session_count"] >= 1:
            break
        time.sleep(0.1)
    assert rep_progress.json()["session_count"] >= 1

    db = SessionLocal()
    cleanup_artifact = db.scalar(
        select(SessionArtifact).where(
            SessionArtifact.session_id == session_id, SessionArtifact.artifact_type == "transcript_cleanup"
        )
    )
    db.close()
    assert cleanup_artifact is not None
