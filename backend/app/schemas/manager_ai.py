from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RepInsightRequest(BaseModel):
    manager_id: str
    rep_id: str
    period_days: int = Field(default=30, ge=1, le=365)


class RepInsightContent(BaseModel):
    headline: str = Field(min_length=1, max_length=120)
    primary_weakness: str = Field(min_length=1, max_length=160)
    root_cause: str = Field(min_length=1, max_length=600)
    drill_recommendation: str = Field(min_length=1, max_length=280)
    coaching_script: str = Field(min_length=1, max_length=1200)
    expected_improvement: str = Field(min_length=1, max_length=240)


class RepInsightResponse(RepInsightContent):
    rep_id: str
    rep_name: str
    generated_at: str
    data_summary: dict[str, Any] = Field(default_factory=dict)


class SessionAnnotationRequest(BaseModel):
    manager_id: str
    session_id: str


class SessionAnnotation(BaseModel):
    turn_id: str
    type: Literal["strength", "weakness"]
    label: str = Field(min_length=1, max_length=80)
    explanation: str = Field(min_length=1, max_length=600)
    coaching_tip: str | None = Field(default=None, max_length=400)


class SessionAnnotationsResponse(BaseModel):
    session_id: str
    generated_at: str
    annotations: list[SessionAnnotation] = Field(default_factory=list)


class TeamCoachingSummaryRequest(BaseModel):
    manager_id: str
    period_days: int = Field(default=30, ge=1, le=365)


class TeamCoachingSummaryContent(BaseModel):
    summary: str = Field(min_length=1, max_length=1200)


class TeamCoachingSummaryResponse(TeamCoachingSummaryContent):
    manager_id: str
    period_days: int
    generated_at: str
    data_summary: dict[str, Any] = Field(default_factory=dict)
