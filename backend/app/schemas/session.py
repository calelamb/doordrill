from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.scorecard import ManagerCoachingNoteResponse, ManagerReviewResponse


class SessionCreateRequest(BaseModel):
    assignment_id: str | None = None
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
    interruption_timeline: list[dict[str, Any]] = Field(default_factory=list)
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    transport_metrics: dict[str, Any] = Field(default_factory=dict)
    scorecard: dict[str, Any] | None
    manager_reviews: list[ManagerReviewResponse] = Field(default_factory=list)
    coaching_notes: list[ManagerCoachingNoteResponse] = Field(default_factory=list)
    latest_coaching_note: ManagerCoachingNoteResponse | None = None
    rep: dict[str, Any] | None = None
    scenario: dict[str, Any] | None = None


class ManagerFeedItem(BaseModel):
    session_id: str
    rep_id: str
    rep_name: str | None = None
    assignment_id: str
    scenario_id: str | None = None
    scenario_name: str | None = None
    overall_score: float | None
    category_scores: dict[str, Any] = Field(default_factory=dict)
    highlights: list[dict[str, Any]] = Field(default_factory=list)
    manager_reviewed: bool
    assignment_status: str
    session_status: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_seconds: int | None = None
    latest_reviewed_at: str | None = None
    latest_coaching_note_preview: str | None = None


class ManagerFeedResponse(BaseModel):
    items: list[ManagerFeedItem]
