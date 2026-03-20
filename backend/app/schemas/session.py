from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.scorecard import CategoryScoreV2, ManagerCoachingNoteResponse, ManagerReviewResponse, ScorecardCategoryGrade


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


RepCategoryScoreValue = float | ScorecardCategoryGrade | CategoryScoreV2 | dict[str, Any]


class GradingMetaResponse(BaseModel):
    status: str
    source: str | None = None
    provisional: bool = False
    confidence: float | None = None
    evidence_quality: str | None = None
    session_complexity: int | None = None
    call_quality: str | None = None
    message: str | None = None


class TechniqueCheckResponse(BaseModel):
    id: str
    label: str
    category: str
    status: str
    kind: str
    evidence_turn_ids: list[str] = Field(default_factory=list)


class RepSessionTranscriptEntryResponse(BaseModel):
    turn_index: int
    rep_text: str
    ai_text: str
    turn_id: str
    objection_tags: list[str] = Field(default_factory=list)
    emotion: str | None = None
    stage: str | None = None


class RepSessionImprovementTargetResponse(BaseModel):
    category: str
    label: str
    target: str
    score: float


class RepSessionScorecardResponse(BaseModel):
    id: str
    overall_score: float
    scorecard_schema_version: str = "v1"
    category_scores: dict[str, RepCategoryScoreValue] = Field(default_factory=dict)
    highlights: list[dict[str, Any]] = Field(default_factory=list)
    ai_summary: str
    evidence_turn_ids: list[str] = Field(default_factory=list)
    weakness_tags: list[str] = Field(default_factory=list)
    technique_checks: list[TechniqueCheckResponse] = Field(default_factory=list)


class RepSessionFeedbackResponse(BaseModel):
    session: SessionResponse
    scorecard: RepSessionScorecardResponse | None = None
    grading_meta: GradingMetaResponse | None = None
    manager_coaching_note: ManagerCoachingNoteResponse | None = None
    transcript: list[RepSessionTranscriptEntryResponse] = Field(default_factory=list)
    improvement_targets: list[RepSessionImprovementTargetResponse] = Field(default_factory=list)


class RepProgressResponse(BaseModel):
    rep_id: str
    rep_name: str | None = None
    rep_email: str | None = None
    rep_avatar_url: str | None = None
    session_count: int = 0
    scored_session_count: int = 0
    completed_drills: int = 0
    average_score: float | None = None
    streak_days: int = 0
    personal_best: float | None = None
    personal_best_session_id: str | None = None
    most_improved_category: str | None = None
    most_improved_delta: float | None = None
    last_scored_session_at: str | None = None


class RepProgressTrendSessionResponse(BaseModel):
    session_id: str
    started_at: str | None = None
    overall_score: float
    category_scores: dict[str, float] = Field(default_factory=dict)


class RepProgressTrendResponse(BaseModel):
    sessions: list[RepProgressTrendSessionResponse] = Field(default_factory=list)
    category_averages: dict[str, float] = Field(default_factory=dict)
    overall_trend: str


class SessionReplayResponse(BaseModel):
    session_id: str
    status: str
    audio_artifacts: list[dict[str, Any]]
    transcript_turns: list[dict[str, Any]]
    objection_timeline: list[dict[str, Any]]
    micro_behavior_timeline: list[dict[str, Any]] = Field(default_factory=list)
    turn_diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    interruption_timeline: list[dict[str, Any]] = Field(default_factory=list)
    stage_timeline: list[dict[str, Any]] = Field(default_factory=list)
    conversational_realism: dict[str, Any] = Field(default_factory=dict)
    transport_metrics: dict[str, Any] = Field(default_factory=dict)
    scorecard: dict[str, Any] | None
    grading_meta: GradingMetaResponse | None = None
    manager_reviews: list[ManagerReviewResponse] = Field(default_factory=list)
    coaching_notes: list[ManagerCoachingNoteResponse] = Field(default_factory=list)
    latest_coaching_note: ManagerCoachingNoteResponse | None = None
    rep: dict[str, Any] | None = None
    scenario: dict[str, Any] | None = None


class TranscriptTurnResponse(BaseModel):
    turn_id: str
    turn_index: int
    speaker: str
    stage: str
    text: str
    started_at: str
    ended_at: str


class StageTimelineEntryResponse(BaseModel):
    stage: str
    entered_at: str
    turn_index: int
    speaker: str


class LiveSessionCard(BaseModel):
    session_id: str
    rep_id: str
    rep_name: str
    scenario_id: str
    scenario_name: str
    scenario_difficulty: int
    started_at: str
    elapsed_seconds: int
    stage: str | None = None
    turn_count: int = 0


class LiveSessionsResponse(BaseModel):
    manager_id: str
    live_sessions: list[LiveSessionCard] = Field(default_factory=list)
    checked_at: str


class LiveSessionRepResponse(BaseModel):
    id: str
    name: str


class LiveSessionScenarioResponse(BaseModel):
    id: str
    name: str
    difficulty: int


class LiveSessionTranscriptResponse(BaseModel):
    session_id: str
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    elapsed_seconds: int = 0
    stage: str | None = None
    turn_count: int = 0
    rep: LiveSessionRepResponse
    scenario: LiveSessionScenarioResponse | None = None
    turns: list[TranscriptTurnResponse] = Field(default_factory=list)
    stage_timeline: list[StageTimelineEntryResponse] = Field(default_factory=list)


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
