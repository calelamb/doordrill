from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    assignment_id: str
    rep_id: str
    scenario_id: str


class SessionResponse(BaseModel):
    id: str
    assignment_id: str
    rep_id: str
    scenario_id: str
    started_at: datetime
    ended_at: datetime | None
    status: str

    model_config = {"from_attributes": True}


class SessionReplayResponse(BaseModel):
    session_id: str
    status: str
    audio_artifacts: list[dict[str, Any]]
    transcript_turns: list[dict[str, Any]]
    objection_timeline: list[dict[str, Any]]
    scorecard: dict[str, Any] | None


class ManagerFeedItem(BaseModel):
    session_id: str
    rep_id: str
    assignment_id: str
    overall_score: float | None
    category_scores: dict[str, float] = Field(default_factory=dict)
    highlights: list[dict[str, Any]] = Field(default_factory=list)
    manager_reviewed: bool
    assignment_status: str
    session_status: str


class ManagerFeedResponse(BaseModel):
    items: list[ManagerFeedItem]
