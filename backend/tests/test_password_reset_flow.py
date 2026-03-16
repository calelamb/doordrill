from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import app.api.auth as auth_api
from app.db.session import SessionLocal
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services.auth_service import AuthService


def test_request_password_reset_always_returns_204_and_masks_unknown_email(client, seed_org, monkeypatch):
    sent_email: dict[str, str] = {}

    def fake_send_password_reset_email(*, email: str, token: str) -> None:
        sent_email["email"] = email
        sent_email["token"] = token

    monkeypatch.setattr(auth_api, "_send_password_reset_email", fake_send_password_reset_email)

    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None
        rep.password_hash = AuthService().hash_password("SecretPass123")
        known_email = rep.email
        db.commit()
    finally:
        db.close()

    missing = client.post(
        "/auth/request-password-reset",
        headers={"X-Test-Client": "password-reset-missing"},
        json={"email": "missing-user@example.com"},
    )
    assert missing.status_code == 204
    assert missing.content == b""

    existing = client.post(
        "/auth/request-password-reset",
        headers={"X-Test-Client": "password-reset-existing"},
        json={"email": known_email},
    )
    assert existing.status_code == 204
    assert existing.content == b""
    assert sent_email["email"] == known_email

    db = SessionLocal()
    try:
        resets = db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == seed_org["rep_id"])).all()
        assert len(resets) == 1
        assert resets[0].token == sent_email["token"]
        assert resets[0].used_at is None
    finally:
        db.close()


def test_reset_password_rejects_expired_or_used_tokens(client, seed_org):
    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None
        rep.password_hash = AuthService().hash_password("SecretPass123")
        db.add_all(
            [
                PasswordResetToken(
                    user_id=rep.id,
                    token="expired-reset-token",
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                ),
                PasswordResetToken(
                    user_id=rep.id,
                    token="used-reset-token",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
                    used_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    expired = client.post(
        "/auth/reset-password",
        headers={"X-Test-Client": "password-reset-expired"},
        json={"token": "expired-reset-token", "new_password": "NextSecret123"},
    )
    assert expired.status_code == 400
    assert expired.json()["detail"] == "Reset link is invalid or expired"

    used = client.post(
        "/auth/reset-password",
        headers={"X-Test-Client": "password-reset-used"},
        json={"token": "used-reset-token", "new_password": "NextSecret123"},
    )
    assert used.status_code == 400
    assert used.json()["detail"] == "Reset link is invalid or expired"


def test_reset_password_is_single_use_and_updates_password(client, seed_org):
    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None
        rep.password_hash = AuthService().hash_password("OldSecret123")
        db.add(
            PasswordResetToken(
                user_id=rep.id,
                token="valid-reset-token",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
            )
        )
        db.commit()
    finally:
        db.close()

    first = client.post(
        "/auth/reset-password",
        headers={"X-Test-Client": "password-reset-first-use"},
        json={"token": "valid-reset-token", "new_password": "NewSecret123"},
    )
    assert first.status_code == 204
    assert first.content == b""

    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token == "valid-reset-token"))
        assert rep is not None
        assert reset is not None
        assert AuthService().verify_password("NewSecret123", rep.password_hash)
        assert reset.used_at is not None
    finally:
        db.close()

    second = client.post(
        "/auth/reset-password",
        headers={"X-Test-Client": "password-reset-second-use"},
        json={"token": "valid-reset-token", "new_password": "AnotherSecret123"},
    )
    assert second.status_code == 400
    assert second.json()["detail"] == "Reset link is invalid or expired"


def test_password_reset_rate_limits(client):
    for _ in range(3):
        response = client.post(
            "/auth/request-password-reset",
            headers={"X-Test-Client": "password-reset-request-limit"},
            json={"email": "limit-check@example.com"},
        )
        assert response.status_code == 204

    limited_request = client.post(
        "/auth/request-password-reset",
        headers={"X-Test-Client": "password-reset-request-limit"},
        json={"email": "limit-check@example.com"},
    )
    assert limited_request.status_code == 429
    assert limited_request.json()["detail"] == "Rate limit exceeded"

    for _ in range(5):
        response = client.post(
            "/auth/reset-password",
            headers={"X-Test-Client": "password-reset-confirm-limit"},
            json={"token": "missing-token", "new_password": "StrongPass123"},
        )
        assert response.status_code == 400

    limited_reset = client.post(
        "/auth/reset-password",
        headers={"X-Test-Client": "password-reset-confirm-limit"},
        json={"token": "missing-token", "new_password": "StrongPass123"},
    )
    assert limited_reset.status_code == 429
    assert limited_reset.json()["detail"] == "Rate limit exceeded"
