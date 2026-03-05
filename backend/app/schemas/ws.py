from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class WsEvent(BaseModel):
    type: str
    sequence: int | None = None
    event_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
