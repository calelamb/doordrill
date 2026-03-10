from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.invitation import Invitation
from app.models.types import UserRole
from app.models.user import Organization, Team, User
from app.schemas.auth import (
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthRegisterRequest,
    AuthTokenResponse,
    AuthUserResponse,
)
from app.schemas.invitation import AcceptInviteRequest, ValidateInviteResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
auth_service = AuthService()


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
    # Always run verify to prevent timing oracle user enumeration
    password_hash = user.password_hash if user else None
    valid = auth_service.verify_password(payload.password, password_hash)
    if not user or not valid:
        raise HTTPException(status_code=401, detail="invalid credentials")

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
