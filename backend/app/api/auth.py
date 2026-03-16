from datetime import datetime, timezone
import asyncio
from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.core.config import get_settings
from app.db.session import get_db
from app.models.invitation import Invitation
from app.models.password_reset import PasswordResetToken
from app.models.types import UserRole
from app.models.user import Organization, Team, User
from app.schemas.auth import (
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthRegisterRequest,
    AuthTokenResponse,
    AuthUserResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from app.schemas.invitation import AcceptInviteRequest, ValidateInviteResponse
from app.services.auth_service import AuthService
from app.services.notification_providers import build_email_provider

router = APIRouter(prefix="/auth", tags=["auth"])
auth_service = AuthService()
settings = get_settings()
password_reset_email_provider = build_email_provider(settings)


def _to_auth_response(user: User, tokens: dict) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        user=AuthUserResponse(
            id=user.id,
            org_id=user.org_id,
            team_id=user.team_id,
            role=user.role.value,
            name=user.name,
            email=user.email,
        ),
    )


def _get_pending_invitation(db: Session, token: str) -> Invitation | None:
    invitation = db.scalar(select(Invitation).where(Invitation.token == token))
    if invitation is None:
        return None
    if invitation.status != "pending":
        return None
    now = datetime.now(timezone.utc)
    expires_at = invitation.expires_at if invitation.expires_at.tzinfo else invitation.expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        invitation.status = "expired"
        db.commit()
        return None
    return invitation


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _send_password_reset_email(*, email: str, token: str) -> None:
    reset_url = f"doordrill://reset-password?token={token}"
    _run_async(
        password_reset_email_provider.send(
            to_email=email,
            subject="Reset your DoorDrill password",
            body=(
                "Tap the link to reset your password (expires in 2 hours):\n\n"
                f"{reset_url}\n\n"
                "If you didn't request this, ignore this email."
            ),
        )
    )


@router.post("/register", response_model=AuthTokenResponse)
def register(payload: AuthRegisterRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    try:
        role = UserRole(payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid role") from exc

    org = db.scalar(select(Organization).where(Organization.id == payload.org_id)) if payload.org_id else None
    if role in {UserRole.MANAGER, UserRole.ADMIN} and org is None:
        org = Organization(
            name=payload.org_name or f"{payload.name}'s Team",
            industry=payload.industry,
            plan_tier="starter",
        )
        db.add(org)
        db.flush()
    if org is None:
        raise HTTPException(status_code=400, detail="org_id is required for rep registration")

    team = db.scalar(select(Team).where(Team.id == payload.team_id)) if payload.team_id else None
    if team and team.org_id != org.id:
        raise HTTPException(status_code=400, detail="team belongs to a different organization")

    user = User(
        org_id=org.id,
        team_id=team.id if team else None,
        role=role,
        name=payload.name,
        email=payload.email.lower(),
        password_hash=auth_service.hash_password(payload.password),
        auth_provider="local",
    )
    db.add(user)
    db.flush()

    if role == UserRole.MANAGER and team is None:
        team = Team(org_id=org.id, manager_id=user.id, name=f"{payload.name} Team")
        db.add(team)
        db.flush()
        user.team_id = team.id

    db.commit()
    db.refresh(user)
    tokens = auth_service.issue_tokens(user)
    return _to_auth_response(user, tokens)


@router.post("/login", response_model=AuthTokenResponse)
def login(payload: AuthLoginRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    password_is_valid = auth_service.verify_password(payload.password, user.password_hash if user else None)
    if user is None or not password_is_valid:
        raise HTTPException(status_code=401, detail="invalid credentials")

    if auth_service.needs_rehash(user.password_hash):
        user.password_hash = auth_service.hash_password(payload.password)
        db.commit()

    tokens = auth_service.issue_tokens(user)
    return _to_auth_response(user, tokens)


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh(payload: AuthRefreshRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    try:
        claims = auth_service.decode_refresh_token(payload.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid refresh token") from exc

    if claims.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="invalid token type")
    user_id = str(claims.get("sub") or claims.get("user_id") or "").strip()
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")

    tokens = auth_service.issue_tokens(user)
    return _to_auth_response(user, tokens)


@router.post("/request-password-reset", status_code=204)
@limiter.limit("3/minute")
def request_password_reset(
    request: Request,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
) -> None:
    del request

    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        return

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    reset = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=expires_at,
    )
    db.add(reset)
    db.commit()
    _send_password_reset_email(email=user.email, token=token)


@router.post("/reset-password", status_code=204)
@limiter.limit("5/minute")
def reset_password(
    request: Request,
    payload: PasswordResetConfirm,
    db: Session = Depends(get_db),
) -> None:
    del request

    reset = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token == payload.token,
            PasswordResetToken.used_at.is_(None),
        )
    )
    if reset is None:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")

    expires_at = reset.expires_at if reset.expires_at.tzinfo else reset.expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")

    user = db.get(User, reset.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="User not found")

    user.password_hash = auth_service.hash_password(payload.new_password)
    reset.used_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/validate-invite", response_model=ValidateInviteResponse)
def validate_invite(
    token: str = Query(..., min_length=16),
    db: Session = Depends(get_db),
) -> ValidateInviteResponse:
    invitation = _get_pending_invitation(db, token)
    if invitation is None:
        raise HTTPException(status_code=400, detail="Invitation is invalid or expired")

    return ValidateInviteResponse(email=invitation.email, org_id=invitation.org_id, valid=True)


@router.post("/accept-invite", response_model=AuthTokenResponse)
def accept_invite(payload: AcceptInviteRequest, db: Session = Depends(get_db)) -> AuthTokenResponse:
    invitation = _get_pending_invitation(db, payload.token)
    if invitation is None:
        raise HTTPException(status_code=400, detail="Invitation is invalid or expired")

    existing = db.scalar(select(User).where(User.email == invitation.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    try:
        role = UserRole(invitation.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid invitation role") from exc

    user = User(
        org_id=invitation.org_id,
        team_id=invitation.team_id,
        role=role,
        name=payload.name,
        email=invitation.email,
        password_hash=auth_service.hash_password(payload.password),
        auth_provider="invite",
    )
    db.add(user)
    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    tokens = auth_service.issue_tokens(user)
    return _to_auth_response(user, tokens)
