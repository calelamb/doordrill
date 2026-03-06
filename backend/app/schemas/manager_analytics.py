from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RepRiskDetail(BaseModel):
    rep_id: str
    rep_name: str
    current_avg_score: float | None = None
    score_trend_slope: float | None = None
    score_volatility: float = 0.0
    projected_score_10_sessions: float | None = None
    plateau_detected: bool = False
    decline_detected: bool = False
    breakthrough_detected: bool = False
    stall_detected: bool = False
    days_since_last_session: int | None = None
    most_vulnerable_category: str | None = None
    category_gap_vs_team: float | None = None
    risk_level: Literal["high", "medium", "low"]
    risk_score: float = 0.0
    session_count: int = 0
    red_flag_count: int = 0


class RepRiskDetailResponse(BaseModel):
    manager_id: str
    period: str
    generated_at: str
    reps: list[RepRiskDetail] = Field(default_factory=list)
    team_avg_score: float | None = None
    team_category_averages: dict[str, float] = Field(default_factory=dict)
