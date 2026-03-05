from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.models.user import User


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def hash_password(self, password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000, dklen=32)
        return f"pbkdf2_sha256$120000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

    def verify_password(self, password: str, password_hash: str | None) -> bool:
        if not password_hash:
            return False
        try:
            scheme, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            salt = base64.urlsafe_b64decode(salt_b64.encode())
            expected_digest = base64.urlsafe_b64decode(digest_b64.encode())
            actual_digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                int(rounds),
                dklen=len(expected_digest),
            )
            return hmac.compare_digest(actual_digest, expected_digest)
        except Exception:
            return False

    def issue_tokens(self, user: User) -> dict:
        if not self.settings.jwt_secret:
            raise ValueError("JWT_SECRET must be configured for auth endpoints")

        now = datetime.now(UTC)
        access_expires = now + timedelta(minutes=self.settings.access_token_ttl_minutes)
        refresh_expires = now + timedelta(days=self.settings.refresh_token_ttl_days)

        access_payload = {
            "sub": user.id,
            "user_id": user.id,
            "role": user.role.value,
            "org_id": user.org_id,
            "team_id": user.team_id,
            "token_type": "access",
            "iat": int(now.timestamp()),
            "exp": int(access_expires.timestamp()),
        }
        refresh_payload = {
            "sub": user.id,
            "user_id": user.id,
            "role": user.role.value,
            "org_id": user.org_id,
            "team_id": user.team_id,
            "token_type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(refresh_expires.timestamp()),
        }
        if self.settings.jwt_audience:
            access_payload["aud"] = self.settings.jwt_audience
            refresh_payload["aud"] = self.settings.jwt_audience
        if self.settings.jwt_issuer:
            access_payload["iss"] = self.settings.jwt_issuer
            refresh_payload["iss"] = self.settings.jwt_issuer

        access_token = jwt.encode(access_payload, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)
        refresh_token = jwt.encode(refresh_payload, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.settings.access_token_ttl_minutes * 60,
        }

    def decode_refresh_token(self, refresh_token: str) -> dict:
        if not self.settings.jwt_secret:
            raise ValueError("JWT_SECRET must be configured for auth endpoints")
        options = {"verify_aud": bool(self.settings.jwt_audience), "verify_iss": bool(self.settings.jwt_issuer)}
        return jwt.decode(
            refresh_token,
            self.settings.jwt_secret,
            algorithms=[self.settings.jwt_algorithm],
            audience=self.settings.jwt_audience,
            issuer=self.settings.jwt_issuer,
            options=options,
        )
