from pydantic import BaseModel, EmailStr, Field


class AuthRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    role: str = Field(pattern="^(rep|manager|admin)$")
    org_id: str | None = None
    team_id: str | None = None
    org_name: str | None = Field(default=None, max_length=255)
    industry: str = Field(default="pest_control", max_length=120)


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AuthRefreshRequest(BaseModel):
    refresh_token: str


class AuthUserResponse(BaseModel):
    id: str
    org_id: str
    team_id: str | None
    role: str
    name: str
    email: str


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserResponse
