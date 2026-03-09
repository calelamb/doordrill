from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class InviteRepRequest(BaseModel):
    email: EmailStr
    team_id: str | None = None
    role: str = Field(default="rep", pattern="^(rep|manager|admin)$")


class InviteRepResponse(BaseModel):
    invitation_id: str
    email: EmailStr
    invite_url: str
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class ValidateInviteResponse(BaseModel):
    email: EmailStr
    org_id: str
    valid: bool = True
