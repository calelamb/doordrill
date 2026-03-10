from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User


@dataclass
class Actor:
    user_id: str | None
    role: str
    org_id: str | None
    team_id: str | None


ALLOWED_ROLES = {"rep", "manager", "admin"}


@lru_cache(maxsize=2)
def _get_jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url)


def _decode_bearer_token(raw_auth: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.jwt_secret and not settings.jwt_jwks_url:
        raise HTTPException(status_code=500, detail="JWT_SECRET or JWT_JWKS_URL is required for token auth")

    if not raw_auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="invalid authorization header format")
    token = raw_auth.split(" ", 1)[1].strip()

    options = {
        "verify_aud": bool(settings.jwt_audience),
        "verify_iss": bool(settings.jwt_issuer),
    }
    try:
        if settings.jwt_jwks_url:
            signing_key = _get_jwks_client(settings.jwt_jwks_url).get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[settings.jwt_algorithm],
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer,
                options=options,
            )
        else:
            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer,
                options=options,
            )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    return payload


def _resolve_identity(
    *,
    x_user_id: str | None,
    x_user_role: str | None,
    authorization: str | None,
) -> tuple[str | None, str | None]:
    settings = get_settings()

    if authorization:
        payload = _decode_bearer_token(authorization)
        user_id = str(payload.get("sub") or payload.get("user_id") or "").strip() or None
        role = str(payload.get("role") or "").lower().strip() or None
        return user_id, role

    if settings.auth_mode.lower() == "jwt" and settings.auth_required:
        raise HTTPException(status_code=401, detail="missing bearer token")

    if x_user_id or x_user_role:
        return x_user_id, x_user_role.lower() if x_user_role else None

    return None, None


def get_actor(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Actor:
    settings = get_settings()
    resolved_user_id, resolved_role = _resolve_identity(
        x_user_id=x_user_id,
        x_user_role=x_user_role,
        authorization=authorization,
    )

    if not resolved_user_id and not resolved_role:
        if settings.auth_required:
            raise HTTPException(status_code=401, detail="missing authentication")
        return Actor(user_id=None, role="admin", org_id=None, team_id=None)

    if not resolved_user_id or not resolved_role:
        raise HTTPException(status_code=401, detail="incomplete authentication identity")
    if resolved_role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="invalid role")

    user = db.scalar(select(User).where(User.id == resolved_user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    if user.role.value != resolved_role and resolved_role != "admin":
        raise HTTPException(status_code=403, detail="role mismatch")

    return Actor(user_id=user.id, role=resolved_role, org_id=user.org_id, team_id=user.team_id)


def resolve_ws_actor(headers) -> Actor:
    """Resolve actor from WebSocket headers without FastAPI DI.

    Returns an admin Actor when auth is not required and no credentials are
    provided, matching the REST ``get_actor`` behaviour.
    """
    settings = get_settings()
    authorization = headers.get("authorization")
    x_user_id = headers.get("x-user-id")
    x_user_role = headers.get("x-user-role")

    resolved_user_id, resolved_role = _resolve_identity(
        x_user_id=x_user_id,
        x_user_role=x_user_role,
        authorization=authorization,
    )

    if not resolved_user_id and not resolved_role:
        if settings.auth_required:
            return None  # type: ignore[return-value]
        return Actor(user_id=None, role="admin", org_id=None, team_id=None)

    if not resolved_user_id or not resolved_role:
        return None  # type: ignore[return-value]
    if resolved_role not in ALLOWED_ROLES:
        return None  # type: ignore[return-value]

    return Actor(user_id=resolved_user_id, role=resolved_role, org_id=None, team_id=None)


def resolve_ws_actor_with_query(headers, query_params, db: Session) -> Actor | None:
    settings = get_settings()
    authorization = headers.get("authorization")
    if not authorization:
        access_token = str(query_params.get("access_token") or "").strip()
        if access_token:
            authorization = f"Bearer {access_token}"

    x_user_id = headers.get("x-user-id")
    x_user_role = headers.get("x-user-role")
    try:
        resolved_user_id, resolved_role = _resolve_identity(
            x_user_id=x_user_id,
            x_user_role=x_user_role,
            authorization=authorization,
        )
    except HTTPException:
        return None

    if not resolved_user_id and not resolved_role:
        if settings.auth_required:
            return None
        return Actor(user_id=None, role="admin", org_id=None, team_id=None)

    if not resolved_user_id or not resolved_role:
        return None
    if resolved_role not in ALLOWED_ROLES:
        return None

    user = db.scalar(select(User).where(User.id == resolved_user_id))
    if user is None:
        return None
    if user.role.value != resolved_role and resolved_role != "admin":
        return None
    return Actor(user_id=user.id, role=resolved_role, org_id=user.org_id, team_id=user.team_id)


def require_manager(actor: Actor = Depends(get_actor)) -> Actor:
    if actor.role not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail="manager role required")
    return actor


def require_admin(actor: Actor = Depends(get_actor)) -> Actor:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return actor


def require_rep_or_manager(actor: Actor = Depends(get_actor)) -> Actor:
    if actor.role not in {"rep", "manager", "admin"}:
        raise HTTPException(status_code=403, detail="rep or manager role required")
    return actor
