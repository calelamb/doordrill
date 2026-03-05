from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from app.core.config import get_settings


@dataclass
class Actor:
    user_id: str | None
    role: str


ALLOWED_ROLES = {"rep", "manager", "admin"}


def get_actor(
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> Actor:
    settings = get_settings()

    if not settings.auth_required and not x_user_role:
        return Actor(user_id=x_user_id, role="admin")

    if not x_user_id or not x_user_role:
        raise HTTPException(status_code=401, detail="missing authentication headers")

    role = x_user_role.lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="invalid role")

    return Actor(user_id=x_user_id, role=role)


def require_manager(actor: Actor = Depends(get_actor)) -> Actor:
    if actor.role not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail="manager role required")
    return actor


def require_rep_or_manager(actor: Actor = Depends(get_actor)) -> Actor:
    if actor.role not in {"rep", "manager", "admin"}:
        raise HTTPException(status_code=403, detail="rep or manager role required")
    return actor
