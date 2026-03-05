from datetime import datetime

from pydantic import BaseModel


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
