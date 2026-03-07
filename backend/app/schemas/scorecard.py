from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScorecardCategoryGrade(BaseModel):
    score: float = Field(ge=0, le=10)
    rationale: str = Field(min_length=1, max_length=400)
    evidence_turn_ids: list[str] = Field(default_factory=list)


class CategoryScoreV2(BaseModel):
    score: float = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    rationale_summary: str = Field(min_length=1, max_length=80)
    rationale_detail: str = Field(min_length=1, max_length=400)
    evidence_turn_ids: list[str] = Field(default_factory=list)
    behavioral_signals: list[str] = Field(default_factory=list)
    improvement_target: str | None = Field(default=None, max_length=60)


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


class StructuredScorecardPayloadV2(BaseModel):
    category_scores: dict[str, CategoryScoreV2]
    overall_score: float = Field(ge=0, le=10)
    highlights: list[ScorecardHighlight] = Field(min_length=2, max_length=4)
    ai_summary: str = Field(min_length=1, max_length=400)
    weakness_tags: list[str] = Field(default_factory=list)
    evidence_quality: Literal["strong", "moderate", "weak"]
    session_complexity: int = Field(ge=1, le=5)


class ScorecardOverrideRequest(BaseModel):
    reviewer_id: str
    reason_code: str
    override_score: float | None = None
    notes: str | None = None


class BulkReviewRequest(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class BulkReviewItemResponse(BaseModel):
    session_id: str
    scorecard_id: str | None = None
    status: str
    review_id: str | None = None


class BulkReviewResponse(BaseModel):
    requested_count: int
    created_count: int
    skipped_count: int
    items: list[BulkReviewItemResponse]


class CoachingNoteCreateRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    visible_to_rep: bool = True
    weakness_tags: list[str] = Field(default_factory=list)


class ScorecardResponse(BaseModel):
    id: str
    session_id: str
    overall_score: float
    scorecard_schema_version: str = "v1"
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
    idempotency_key: str | None = None

    model_config = {"from_attributes": True}


class ManagerCoachingNoteResponse(BaseModel):
    id: str
    scorecard_id: str
    reviewer_id: str
    note: str
    visible_to_rep: bool
    weakness_tags: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
