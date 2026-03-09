from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

import app.api.manager as manager_api
from app.db.session import SessionLocal
from app.models.invitation import Invitation
from app.models.user import User


def test_manager_invite_creates_pending_invitation_and_sends_email(client, seed_org, monkeypatch):
    sent_email: dict[str, object] = {}

    def fake_send_invitation_email(*, manager_name: str, email: str, invite_url: str, expires_at: datetime) -> None:
        sent_email["manager_name"] = manager_name
        sent_email["email"] = email
        sent_email["invite_url"] = invite_url
        sent_email["expires_at"] = expires_at

    monkeypatch.setattr(manager_api, "_send_invitation_email", fake_send_invitation_email)

    response = client.post(
        "/manager/invitations",
        json={"email": "new-rep@example.com"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "new-rep@example.com"
    assert body["invite_url"].startswith("doordrill://invite?")
    assert sent_email["manager_name"] == "Mia Manager"
    assert sent_email["email"] == "new-rep@example.com"
    assert sent_email["invite_url"] == body["invite_url"]

    parsed = urlparse(body["invite_url"])
    query = parse_qs(parsed.query)
    token = query["token"][0]
    assert len(token) == 32

    db = SessionLocal()
    try:
        invitation = db.scalar(select(Invitation).where(Invitation.id == body["invitation_id"]))
        assert invitation is not None
        assert invitation.email == "new-rep@example.com"
        assert invitation.token == token
        assert invitation.status == "pending"
    finally:
        db.close()


def test_validate_and_accept_invite_returns_tokens_and_marks_invitation_accepted(client, seed_org, monkeypatch):
    monkeypatch.setattr(manager_api, "_send_invitation_email", lambda **_kwargs: None)

    created = client.post(
        "/manager/invitations",
        json={"email": "invited-rep@example.com"},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert created.status_code == 200
    invite_url = created.json()["invite_url"]
    token = parse_qs(urlparse(invite_url).query)["token"][0]

    validated = client.get("/auth/validate-invite", params={"token": token})
    assert validated.status_code == 200
    assert validated.json() == {
        "email": "invited-rep@example.com",
        "org_id": seed_org["org_id"],
        "valid": True,
    }

    accepted = client.post(
        "/auth/accept-invite",
        json={"token": token, "name": "Invited Rep", "password": "SecretPass123"},
    )
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    assert accepted_body["access_token"]
    assert accepted_body["refresh_token"]
    assert accepted_body["user"]["email"] == "invited-rep@example.com"
    assert accepted_body["user"]["org_id"] == seed_org["org_id"]

    db = SessionLocal()
    try:
        invitation = db.scalar(select(Invitation).where(Invitation.token == token))
        user = db.scalar(select(User).where(User.email == "invited-rep@example.com"))
        assert invitation is not None
        assert invitation.status == "accepted"
        assert invitation.accepted_at is not None
        assert user is not None
        assert user.auth_provider == "invite"
    finally:
        db.close()

    second_attempt = client.post(
        "/auth/accept-invite",
        json={"token": token, "name": "Invited Rep", "password": "SecretPass123"},
    )
    assert second_attempt.status_code == 400
    assert second_attempt.json()["detail"] == "Invitation is invalid or expired"


def test_validate_invite_rejects_expired_tokens(client, seed_org):
    db = SessionLocal()
    try:
        expired = Invitation(
            org_id=seed_org["org_id"],
            team_id=None,
            invited_by=seed_org["manager_id"],
            email="expired-invite@example.com",
            token="expired-token-1234567890abcdef",
            role="rep",
            status="pending",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(expired)
        db.commit()
    finally:
        db.close()

    response = client.get("/auth/validate-invite", params={"token": "expired-token-1234567890abcdef"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invitation is invalid or expired"

    db = SessionLocal()
    try:
        invitation = db.scalar(select(Invitation).where(Invitation.token == "expired-token-1234567890abcdef"))
        assert invitation is not None
        assert invitation.status == "expired"
    finally:
        db.close()
