from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AssignmentCreateRequest(BaseModel):
    scenario_id: str
    rep_id: str
    assigned_by: str
    due_at: datetime | None = None
    min_score_target: float | None = None
    retry_policy: dict[str, Any] = Field(default_factory=dict)


class FollowupAssignmentRequest(BaseModel):
    scenario_id: str
    assigned_by: str
    due_at: datetime | None = None
    min_score_target: float | None = None
    retry_policy: dict[str, Any] = Field(default_factory=lambda: {"max_attempts": 1})


class AssignmentResponse(BaseModel):
    id: str
    scenario_id: str
    rep_id: str
    assigned_by: str
    due_at: datetime | None
    status: str
    min_score_target: float | None
    retry_policy: dict[str, Any]

    model_config = {"from_attributes": True}
