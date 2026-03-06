from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.assignment import AssignmentResponse


class SkillNodeResponse(BaseModel):
    skill: str
    score: float
    trend: float
    confidence: float
    contributing_metrics: list[str] = Field(default_factory=list)


class SkillEdgeResponse(BaseModel):
    from_skill: str
    to_skill: str
    weight: float
    rationale: str


class PatienceWindowResponse(BaseModel):
    label: str
    score: int


class DifficultyFactorsResponse(BaseModel):
    objection_frequency: int
    homeowner_resistance_level: int
    patience_window: PatienceWindowResponse
    scenario_complexity: int


class ScenarioRecommendationResponse(BaseModel):
    scenario_id: str
    scenario_name: str
    difficulty: int
    recommendation_score: float
    focus_skills: list[str] = Field(default_factory=list)
    target_weaknesses: list[str] = Field(default_factory=list)
    difficulty_factors: DifficultyFactorsResponse
    rationale: str


class AdaptiveTrainingPlanResponse(BaseModel):
    rep_id: str
    session_count: int
    readiness_score: float
    performance_trend: float
    recommended_difficulty: int
    weakest_skills: list[str] = Field(default_factory=list)
    target_difficulty_factors: DifficultyFactorsResponse
    skill_profile: list[SkillNodeResponse] = Field(default_factory=list)
    skill_graph: list[SkillEdgeResponse] = Field(default_factory=list)
    recommended_scenarios: list[ScenarioRecommendationResponse] = Field(default_factory=list)


class AdaptiveAssignmentRequest(BaseModel):
    assigned_by: str
    scenario_id: str | None = None
    due_at: datetime | None = None
    min_score_target: float | None = None
    retry_policy: dict[str, Any] = Field(default_factory=lambda: {"max_attempts": 2})


class AdaptiveAssignmentResponse(BaseModel):
    assignment: AssignmentResponse
    adaptive_plan: AdaptiveTrainingPlanResponse
    selected_scenario: ScenarioRecommendationResponse
