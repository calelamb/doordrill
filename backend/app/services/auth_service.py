from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.models.user import User

_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
_DUMMY_ARGON2_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "IWyL3I+Cuiyuc8NO/MtM5g$"
    "IJm9zjXYGa8VxLX4VRbGkSfIFbqPyUN+YK+FLewD/w0"
)


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def hash_password(self, password: str) -> str:
        return _password_hasher.hash(password)

    def verify_password(self, password: str, password_hash: str | None) -> bool:
        if not password_hash:
            try:
                _password_hasher.verify(_DUMMY_ARGON2_HASH, password)
            except (VerifyMismatchError, VerificationError, Argon2Error):
                pass
            return False
        if password_hash.startswith("pbkdf2_sha256$"):
            return self._verify_pbkdf2(password, password_hash)
        try:
            return _password_hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, Argon2Error):
            return False

    def needs_rehash(self, password_hash: str | None) -> bool:
        if not password_hash:
            return False
        if password_hash.startswith("pbkdf2_sha256$"):
            return True
        try:
            return _password_hasher.check_needs_rehash(password_hash)
        except Argon2Error:
            return False

    @staticmethod
    def _verify_pbkdf2(password: str, password_hash: str) -> bool:
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
