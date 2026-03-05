from __future__ import annotations

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.types import UserRole
from app.models.user import User
from app.services.auth_service import AuthService


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _issue_access_token(user_id: str) -> str:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        assert user is not None
        return AuthService().issue_tokens(user)["access_token"]
    finally:
        db.close()


def _create_session(client, seed_org: dict[str, str], manager_token: str, rep_token: str) -> str:
    assignment = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "retry_policy": {"max_attempts": 1},
        },
        headers=_auth_headers(manager_token),
    )
    assert assignment.status_code == 200
    assignment_id = assignment.json()["id"]

    session = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
        headers=_auth_headers(rep_token),
    )
    assert session.status_code == 200
    return session.json()["id"]


def _enable_jwt_mode():
    settings = get_settings()
    snapshot = (settings.auth_required, settings.auth_mode)
    settings.auth_required = True
    settings.auth_mode = "jwt"
    return settings, snapshot


def _restore_auth_mode(settings, snapshot) -> None:
    settings.auth_required, settings.auth_mode = snapshot


def test_ws_accepts_jwt_query_param(client, seed_org):
    settings, snapshot = _enable_jwt_mode()
    try:
        manager_token = _issue_access_token(seed_org["manager_id"])
        rep_token = _issue_access_token(seed_org["rep_id"])
        session_id = _create_session(client, seed_org, manager_token, rep_token)

        with client.websocket_connect(f"/ws/sessions/{session_id}?access_token={rep_token}") as ws:
            connected = ws.receive_json()
            assert connected["type"] == "server.session.state"
            ws.send_json({"type": "client.session.end", "sequence": 1, "payload": {}})
    finally:
        _restore_auth_mode(settings, snapshot)


def test_ws_accepts_authorization_header_fallback(client, seed_org):
    settings, snapshot = _enable_jwt_mode()
    try:
        manager_token = _issue_access_token(seed_org["manager_id"])
        rep_token = _issue_access_token(seed_org["rep_id"])
        session_id = _create_session(client, seed_org, manager_token, rep_token)

        with client.websocket_connect(
            f"/ws/sessions/{session_id}",
            headers=_auth_headers(rep_token),
        ) as ws:
            connected = ws.receive_json()
            assert connected["type"] == "server.session.state"
            ws.send_json({"type": "client.session.end", "sequence": 1, "payload": {}})
    finally:
        _restore_auth_mode(settings, snapshot)


def test_ws_rejects_missing_or_wrong_rep_token_and_allows_admin(client, seed_org):
    settings, snapshot = _enable_jwt_mode()
    db = SessionLocal()
    try:
        other_rep = User(
            org_id=seed_org["org_id"],
            team_id=None,
            role=UserRole.REP,
            name="Other Rep",
            email="other-rep@example.com",
            auth_provider="local",
        )
        admin = User(
            org_id=seed_org["org_id"],
            team_id=None,
            role=UserRole.ADMIN,
            name="Admin User",
            email="admin@example.com",
            auth_provider="local",
        )
        db.add_all([other_rep, admin])
        db.commit()
        db.refresh(other_rep)
        db.refresh(admin)

        manager_token = _issue_access_token(seed_org["manager_id"])
        rep_token = _issue_access_token(seed_org["rep_id"])
        other_rep_token = _issue_access_token(other_rep.id)
        admin_token = _issue_access_token(admin.id)
        session_id = _create_session(client, seed_org, manager_token, rep_token)

        with pytest.raises(WebSocketDisconnect) as missing_exc:
            with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
                ws.receive_json()
        assert missing_exc.value.code == 4401

        with pytest.raises(WebSocketDisconnect) as wrong_rep_exc:
            with client.websocket_connect(f"/ws/sessions/{session_id}?access_token={other_rep_token}") as ws:
                ws.receive_json()
        assert wrong_rep_exc.value.code == 4403

        with client.websocket_connect(f"/ws/sessions/{session_id}?access_token={admin_token}") as ws:
            connected = ws.receive_json()
            assert connected["type"] == "server.session.state"
            ws.send_json({"type": "client.session.end", "sequence": 1, "payload": {}})
    finally:
        db.close()
        _restore_auth_mode(settings, snapshot)
