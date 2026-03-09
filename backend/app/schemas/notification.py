from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationPreferences(BaseModel):
    score_ready: bool = True
    assignment_created: bool = True
    assignment_due_soon: bool = True
    coaching_note: bool = True
    streak_nudge: bool = True

    model_config = {"extra": "forbid"}


class DeviceTokenCreateRequest(BaseModel):
    platform: str = Field(pattern="^(ios|android)$")
    provider: str = Field(default="expo", pattern="^(expo|fcm)$")
    token: str = Field(min_length=20, max_length=512)


class DeviceTokenResponse(BaseModel):
    id: str
    user_id: str
    platform: str
    provider: str
    token: str
    status: str
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class NotificationDeliveryResponse(BaseModel):
    id: str
    session_id: str | None
    manager_id: str
    channel: str
    payload: dict[str, Any]
    provider_response: dict[str, Any]
    status: str
    retries: int
    next_retry_at: datetime | None
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime
