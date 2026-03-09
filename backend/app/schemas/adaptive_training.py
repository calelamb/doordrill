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
    history: list[float] = Field(default_factory=list)


class SkillForecastResponse(BaseModel):
    skill: str
    current_score: float | None = None
    velocity: float | None = None
    sessions_to_readiness: int | None = None
    projected_ready_at_sessions: int | None = None
    readiness_threshold: float
    sample_size: int
    r_squared: float | None = None
    forecast_computed_at: datetime | None = None


class CohortBenchmarkSkillResponse(BaseModel):
    skill: str
    current_score: float | None = None
    cohort_mean: float | None = None
    cohort_p25: float | None = None
    cohort_p50: float | None = None
    cohort_p75: float | None = None
    percentile_in_cohort: float | None = None
    percentile_in_org: float | None = None
    interpretation: str | None = None


class RepCohortBenchmarkResponse(BaseModel):
    rep_id: str
    cohort_label: str | None = None
    cohort_size: int = 0
    skills: list[CohortBenchmarkSkillResponse] = Field(default_factory=list)


class RepForecastResponse(BaseModel):
    rep_id: str
    readiness_score: float | None = None
    overall_velocity: float | None = None
    overall_sessions_to_readiness: int | None = None
    skill_forecasts: list[SkillForecastResponse] = Field(default_factory=list)
    forecast_computed_at: datetime | None = None
    cohort_benchmarks: RepCohortBenchmarkResponse | None = None


class TeamForecastSummaryResponse(BaseModel):
    rep_id: str
    name: str
    readiness_score: float | None = None
    sessions_to_readiness: int | None = None
    velocity: float | None = None
    forecast_computed_at: datetime | None = None


class TeamForecastResponse(BaseModel):
    manager_id: str
    team_size: int
    avg_sessions_to_readiness: float | None = None
    median_sessions_to_readiness: float | None = None
    reps_already_ready: int
    reps_on_track: int
    reps_at_risk: int
    rep_summaries: list[TeamForecastSummaryResponse] = Field(default_factory=list)


class TeamIntelligenceAtRiskRepResponse(BaseModel):
    rep_id: str
    name: str
    risk_level: str
    triggered_alerts: list[str] = Field(default_factory=list)
    days_since_last_session: int | None = None


class TeamIntelligenceCohortComparisonResponse(BaseModel):
    reps_above_cohort_median: int = 0
    reps_below_cohort_median: int = 0


class TeamIntelligenceCoachingEffectivenessResponse(BaseModel):
    avg_score_delta: float = 0.0
    positive_impact_rate: float = 0.0


class TeamIntelligenceProjectionWindowResponse(BaseModel):
    projected_avg_score: float = 0.0
    reps_reaching_readiness: int = 0


class TeamIntelligenceSnapshotResponse(BaseModel):
    manager_id: str
    org_id: str
    snapshot_at: datetime
    team_size: int = 0
    avg_readiness_score: float = 0.0
    reps_ready: int = 0
    reps_on_track: int = 0
    reps_at_risk: int = 0
    projected_team_readiness_in_sessions: float = 0.0
    team_skill_averages: dict[str, float] = Field(default_factory=dict)
    weakest_team_skill: str | None = None
    strongest_team_skill: str | None = None
    at_risk_reps: list[TeamIntelligenceAtRiskRepResponse] = Field(default_factory=list)
    cohort_comparison: TeamIntelligenceCohortComparisonResponse
    coaching_effectiveness: TeamIntelligenceCoachingEffectivenessResponse
    projection: dict[str, TeamIntelligenceProjectionWindowResponse] = Field(default_factory=dict)


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
    outcome_boost: bool = False
    avg_skill_delta_historical: float | None = None
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
    readiness_forecast: list[SkillForecastResponse] = Field(default_factory=list)
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
