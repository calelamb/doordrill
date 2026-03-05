from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScorecardCategoryGrade(BaseModel):
    score: float = Field(ge=0, le=10)
    rationale: str = Field(min_length=1, max_length=400)
    evidence_turn_ids: list[str] = Field(default_factory=list)


class ScorecardHighlight(BaseModel):
    type: Literal["strong", "improve"]
    note: str = Field(min_length=1, max_length=240)
    turn_id: str | None = None


class StructuredScorecardPayload(BaseModel):
    category_scores: dict[str, ScorecardCategoryGrade]
    overall_score: float = Field(ge=0, le=10)
    highlights: list[ScorecardHighlight] = Field(min_length=2, max_length=4)
    ai_summary: str = Field(min_length=1, max_length=400)
    evidence_turn_ids: list[str] = Field(default_factory=list)
    weakness_tags: list[str] = Field(default_factory=list)


class ScorecardOverrideRequest(BaseModel):
    reviewer_id: str
    reason_code: str
    override_score: float | None = None
    notes: str | None = None


class ScorecardResponse(BaseModel):
    id: str
    session_id: str
    overall_score: float
    category_scores: dict
    highlights: list[dict]
    ai_summary: str
    evidence_turn_ids: list[str]
    weakness_tags: list[str]

    model_config = {"from_attributes": True}


class ManagerReviewResponse(BaseModel):
    id: str
    scorecard_id: str
    reviewer_id: str
    reviewed_at: datetime
    reason_code: str
    override_score: float | None
    notes: str | None

    model_config = {"from_attributes": True}
