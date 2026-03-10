import base64
import hashlib
import os

from sqlalchemy import select

from app.core.auth import _decode_bearer_token
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.auth_service import AuthService


def _legacy_pbkdf2_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000, dklen=32)
    return (
        "pbkdf2_sha256$120000$"
        f"{base64.urlsafe_b64encode(salt).decode()}$"
        f"{base64.urlsafe_b64encode(digest).decode()}"
    )


def test_login_rehashes_legacy_passwords(client, seed_org):
    legacy_hash = _legacy_pbkdf2_hash("SecretPass123")
    rep_email = ""

    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None
        rep_email = rep.email
        rep.password_hash = legacy_hash
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/auth/login",
        json={"email": rep_email, "password": "SecretPass123"},
    )

    assert response.status_code == 200

    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None
        assert rep.password_hash != legacy_hash
        assert not rep.password_hash.startswith("pbkdf2_sha256$")
        assert AuthService().verify_password("SecretPass123", rep.password_hash)
    finally:
        db.close()


def test_decode_bearer_token_rejects_unsupported_algorithms():
    settings = get_settings()
    original_algorithm = settings.jwt_algorithm
    try:
        settings.jwt_algorithm = "none"
        try:
            _decode_bearer_token("Bearer fake-token")
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 500
            assert getattr(exc, "detail", "") == "unsupported JWT algorithm configured"
        else:
            raise AssertionError("expected unsupported algorithm to be rejected")
    finally:
        settings.jwt_algorithm = original_algorithm
