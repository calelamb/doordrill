from __future__ import annotations

from pydantic import BaseModel, Field


class AiAttemptMeta(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=160)
    outcome: str = Field(min_length=1, max_length=64)
    latency_ms: int = Field(ge=0)
    real_call: bool
    task: str | None = Field(default=None, max_length=64)
    error: str | None = Field(default=None, max_length=240)


class AiMeta(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=160)
    real_call: bool
    cached: bool = False
    status: str = Field(min_length=1, max_length=64)
    latency_ms: int = Field(ge=0)
    fallback_used: bool = False
    fallback_kind: str | None = Field(default=None, max_length=32)
    attempts: list[AiAttemptMeta] = Field(default_factory=list)
    generated_at: str
