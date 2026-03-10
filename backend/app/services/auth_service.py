from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.models.user import User

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def hash_password(self, password: str) -> str:
        """Hash a password using argon2id."""
        return _ph.hash(password)

    def verify_password(self, password: str, password_hash: str | None) -> bool:
        """Verify a password against a stored hash.

        Supports both argon2id (new) and legacy pbkdf2_sha256 hashes.
        Returns True if the password matches. Callers should check
        needs_rehash() to transparently upgrade legacy hashes.
        """
        if not password_hash:
            return False

        # Legacy PBKDF2 hash format: pbkdf2_sha256$rounds$salt$digest
        if password_hash.startswith("pbkdf2_sha256$"):
            return self._verify_pbkdf2(password, password_hash)

        # Argon2id hash format
        try:
            return _ph.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str | None) -> bool:
        """Check if a password hash should be upgraded to argon2id."""
        if not password_hash:
            return False
        # Any legacy PBKDF2 hash needs rehashing
        if password_hash.startswith("pbkdf2_sha256$"):
            return True
        # Check if argon2 params have changed
        try:
            return _ph.check_needs_rehash(password_hash)
        except Exception:
            return False

    @staticmethod
    def _verify_pbkdf2(password: str, password_hash: str) -> bool:
        """Verify a legacy PBKDF2-SHA256 hash."""
        try:
            scheme, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            rounds_int = int(rounds)
            if not (1000 <= rounds_int <= 1_000_000):
                return False
            salt = base64.urlsafe_b64decode(salt_b64.encode())
            expected_digest = base64.urlsafe_b64decode(digest_b64.encode())
            actual_digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                rounds_int,
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
