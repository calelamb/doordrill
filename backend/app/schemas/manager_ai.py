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
    readiness_trajectory: dict[str, Any] = Field(default_factory=dict)
    override_signal: dict[str, Any] = Field(default_factory=dict)
    adaptive_skill_profile: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: str | None = Field(default=None, max_length=16)
    triggered_alerts: list[str] = Field(default_factory=list)


class RepInsightResponse(RepInsightContent):
    rep_id: str
    rep_name: str
    generated_at: str
    data_summary: dict[str, Any] = Field(default_factory=dict)


class OneOnOnePrepRequest(BaseModel):
    manager_id: str
    period_days: int = Field(default=14, ge=1, le=365)


class OneOnOneDiscussionTopic(BaseModel):
    topic: str = Field(min_length=1, max_length=160)
    evidence: str = Field(min_length=1, max_length=400)
    suggested_opener: str = Field(min_length=1, max_length=400)


class OneOnOneStrengthToAcknowledge(BaseModel):
    skill: str = Field(min_length=1, max_length=80)
    what_to_say: str = Field(min_length=1, max_length=500)


class OneOnOnePatternToChallenge(BaseModel):
    skill: str = Field(min_length=1, max_length=80)
    pattern: str = Field(min_length=1, max_length=400)
    what_to_say: str = Field(min_length=1, max_length=500)


class OneOnOneSuggestedNextScenario(BaseModel):
    scenario_type: str = Field(min_length=1, max_length=160)
    difficulty: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1, max_length=400)


class OneOnOnePrepContent(BaseModel):
    discussion_topics: list[OneOnOneDiscussionTopic] = Field(default_factory=list, min_length=3, max_length=3)
    strength_to_acknowledge: OneOnOneStrengthToAcknowledge
    pattern_to_challenge: OneOnOnePatternToChallenge
    suggested_next_scenario: OneOnOneSuggestedNextScenario
    readiness_summary: str = Field(min_length=1, max_length=320)


class OneOnOnePrepResponse(OneOnOnePrepContent):
    manager_id: str
    rep_id: str
    rep_name: str
    period_days: int
    generated_at: str
    data_summary: dict[str, Any] = Field(default_factory=dict)


class WeeklyTeamBriefingRequest(BaseModel):
    manager_id: str


class WeeklyTeamBriefingStandoutRep(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    why: str = Field(min_length=1, max_length=400)


class WeeklyTeamBriefingNeedsAttentionItem(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    concern: str = Field(min_length=1, max_length=400)


class WeeklyTeamBriefingSharedWeakness(BaseModel):
    skill: str = Field(min_length=1, max_length=80)
    team_average: float
    note: str = Field(min_length=1, max_length=320)


class WeeklyTeamBriefingHuddleTopic(BaseModel):
    topic: str = Field(min_length=1, max_length=180)
    suggested_talking_points: list[str] = Field(default_factory=list, min_length=3, max_length=3)


class WeeklyTeamBriefingResponse(BaseModel):
    manager_id: str
    generated_at: str
    team_pulse: str = Field(min_length=1, max_length=500)
    standout_rep: WeeklyTeamBriefingStandoutRep
    needs_attention: list[WeeklyTeamBriefingNeedsAttentionItem] = Field(default_factory=list, max_length=2)
    shared_weakness: WeeklyTeamBriefingSharedWeakness
    huddle_topic: WeeklyTeamBriefingHuddleTopic
    manager_action_items: list[str] = Field(default_factory=list, min_length=1, max_length=4)
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


class ManagerChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ManagerChatRequest(BaseModel):
    manager_id: str
    message: str = Field(min_length=1, max_length=4000)
    conversation_history: list[ManagerChatHistoryItem] = Field(default_factory=list)
    period_days: int = Field(default=30, ge=1, le=365)


class ManagerChatClassification(BaseModel):
    intent: Literal[
        "team_performance",
        "rep_specific",
        "scenario_analysis",
        "coaching_effectiveness",
        "risk_alerts",
        "comparison",
        "general",
    ]
    rep_name_mentioned: str | None = Field(default=None, max_length=160)
    scenario_mentioned: str | None = Field(default=None, max_length=160)
    category_mentioned: str | None = Field(default=None, max_length=80)


class ChatDataPoint(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=160)


class ManagerChatAnswerContent(BaseModel):
    answer: str = Field(min_length=1, max_length=1200)
    key_metric: str | None = Field(default=None, max_length=120)
    key_metric_label: str | None = Field(default=None, max_length=120)
    follow_up_suggestions: list[str] = Field(default_factory=list)
    action_suggestion: str | None = Field(default=None, max_length=240)
    data_points: list[ChatDataPoint] = Field(default_factory=list)


class ManagerChatResponse(ManagerChatAnswerContent):
    intent_detected: str
    sources_used: list[str] = Field(default_factory=list)
