import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class AnalyticsRefreshRun(Base, TimestampMixin):
    __tablename__ = "analytics_refresh_runs"
    __table_args__ = (
        Index("ix_analytics_refresh_scope_started", "scope_type", "scope_id", "started_at"),
        Index("ix_analytics_refresh_status_started", "status", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)  # session | manager | global
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    row_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsMetricDefinition(Base, TimestampMixin):
    __tablename__ = "analytics_metric_definitions"

    metric_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)  # team | rep | scenario | manager
    aggregation_method: Mapped[str] = mapped_column(String(40), nullable=False)
    owner: Mapped[str] = mapped_column(String(80), nullable=False, default="analytics-platform")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AnalyticsMetricSnapshot(Base, TimestampMixin):
    __tablename__ = "analytics_metric_snapshots"
    __table_args__ = (
        UniqueConstraint("metric_key", "entity_type", "entity_id", "snapshot_date", name="uq_analytics_metric_snapshot"),
        Index("ix_analytics_metric_entity_date", "entity_type", "entity_id", "snapshot_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    metric_key: Mapped[str] = mapped_column(ForeignKey("analytics_metric_definitions.metric_key", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AnalyticsDimManager(Base, TimestampMixin):
    __tablename__ = "analytics_dim_managers"
    __table_args__ = (
        Index("ix_analytics_dim_managers_org_team", "org_id", "team_id"),
    )

    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    manager_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_email: Mapped[str] = mapped_column(String(320), nullable=False)
    rep_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsDimRep(Base, TimestampMixin):
    __tablename__ = "analytics_dim_reps"
    __table_args__ = (
        Index("ix_analytics_dim_reps_manager_team", "manager_id", "team_id"),
    )

    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    rep_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rep_email: Mapped[str] = mapped_column(String(320), nullable=False)
    first_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsDimTeam(Base, TimestampMixin):
    __tablename__ = "analytics_dim_teams"
    __table_args__ = (
        Index("ix_analytics_dim_teams_org_manager", "org_id", "manager_id"),
    )

    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    team_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rep_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsDimScenario(Base, TimestampMixin):
    __tablename__ = "analytics_dim_scenarios"
    __table_args__ = (
        Index("ix_analytics_dim_scenarios_org_industry", "org_id", "industry"),
    )

    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalyticsDimTime(Base, TimestampMixin):
    __tablename__ = "analytics_dim_time"
    __table_args__ = (
        Index("ix_analytics_dim_time_month", "year", "month"),
        Index("ix_analytics_dim_time_iso_week", "iso_year", "iso_week"),
    )

    day_date: Mapped[date] = mapped_column(Date, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AnalyticsFactSession(Base, TimestampMixin):
    __tablename__ = "analytics_fact_sessions"
    __table_args__ = (
        Index("ix_analytics_fact_sessions_manager_date", "manager_id", "session_date"),
        Index("ix_analytics_fact_sessions_rep_date", "rep_id", "session_date"),
        Index("ix_analytics_fact_sessions_scenario_date", "scenario_id", "session_date"),
        Index("ix_analytics_fact_sessions_team_date", "team_id", "session_date"),
    )

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True, nullable=False)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty_adjusted_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opening_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pitch_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    objection_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    professionalism_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rep_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rep_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    talk_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    barge_in_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objection_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    close_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weak_area_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manager_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coaching_note_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_coaching_note_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    weakness_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    objection_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class AnalyticsFactSessionTurnMetrics(Base, TimestampMixin):
    __tablename__ = "analytics_fact_session_turn_metrics"
    __table_args__ = (
        Index("ix_analytics_fact_turn_metrics_manager_date", "manager_id", "session_date"),
    )

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    average_rep_turn_words: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_ai_turn_words: Mapped[float | None] = mapped_column(Float, nullable=True)
    longest_rep_turn_words: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_ai_turn_words: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interruption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objection_tag_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AnalyticsFactRepDay(Base, TimestampMixin):
    __tablename__ = "analytics_fact_rep_day"
    __table_args__ = (
        UniqueConstraint("manager_id", "rep_id", "day_date", name="uq_analytics_rep_day"),
        Index("ix_analytics_fact_rep_day_manager_date", "manager_id", "day_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_coverage_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_talk_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_barge_in_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_close_attempts: Mapped[float | None] = mapped_column(Float, nullable=True)
    weak_area_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class AnalyticsFactRepWeek(Base, TimestampMixin):
    __tablename__ = "analytics_fact_rep_week"
    __table_args__ = (
        UniqueConstraint("manager_id", "rep_id", "week_start", name="uq_analytics_rep_week"),
        Index("ix_analytics_fact_rep_week_manager_date", "manager_id", "week_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_coverage_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_volatility: Mapped[float | None] = mapped_column(Float, nullable=True)
    weak_area_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class AnalyticsFactTeamDay(Base, TimestampMixin):
    __tablename__ = "analytics_fact_team_day"
    __table_args__ = (
        UniqueConstraint("manager_id", "team_id", "day_date", name="uq_analytics_team_day"),
        Index("ix_analytics_fact_team_day_manager_date", "manager_id", "day_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    assignment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_assignment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_rep_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    completion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_coverage_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    red_flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AnalyticsFactScenarioDay(Base, TimestampMixin):
    __tablename__ = "analytics_fact_scenario_day"
    __table_args__ = (
        UniqueConstraint("manager_id", "scenario_id", "day_date", name="uq_analytics_scenario_day"),
        Index("ix_analytics_fact_scenario_day_manager_date", "manager_id", "day_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True, nullable=False)
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rep_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_barge_in_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_weakness_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    top_objection_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class AnalyticsFactCoachingIntervention(Base, TimestampMixin):
    __tablename__ = "analytics_fact_coaching_interventions"
    __table_args__ = (
        Index("ix_analytics_fact_coaching_manager_created", "manager_id", "note_created_at"),
        Index("ix_analytics_fact_coaching_rep_created", "rep_id", "note_created_at"),
    )

    coaching_note_id: Mapped[str] = mapped_column(ForeignKey("manager_coaching_notes.id", ondelete="CASCADE"), primary_key=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    scorecard_id: Mapped[str] = mapped_column(ForeignKey("scorecards.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    next_session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), index=True, nullable=True)
    note_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    visible_to_rep: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    before_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    weakness_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class AnalyticsFactManagerCalibration(Base, TimestampMixin):
    __tablename__ = "analytics_fact_manager_calibration"
    __table_args__ = (
        Index("ix_analytics_fact_calibration_manager_reviewed", "manager_id", "reviewed_at"),
    )

    review_id: Mapped[str] = mapped_column(ForeignKey("manager_reviews.id", ondelete="CASCADE"), primary_key=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    scorecard_id: Mapped[str] = mapped_column(ForeignKey("scorecards.id", ondelete="CASCADE"), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    override_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)


class AnalyticsFactAlert(Base, TimestampMixin):
    __tablename__ = "analytics_fact_alerts"
    __table_args__ = (
        UniqueConstraint("manager_id", "period_key", "alert_key", name="uq_analytics_fact_alert"),
        Index("ix_analytics_fact_alert_manager_period", "manager_id", "period_key", "is_active", "occurred_at"),
        Index("ix_analytics_fact_alert_manager_severity", "manager_id", "severity", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    alert_key: Mapped[str] = mapped_column(String(160), nullable=False)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    period_key: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rep_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id", ondelete="SET NULL"), index=True, nullable=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), index=True, nullable=True)
    focus_turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AnalyticsMaterializedView(Base, TimestampMixin):
    __tablename__ = "analytics_materialized_views"
    __table_args__ = (
        UniqueConstraint("view_name", "manager_id", "period_key", name="uq_analytics_materialized_view"),
        Index("ix_analytics_materialized_manager_view", "manager_id", "view_name", "refreshed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    view_name: Mapped[str] = mapped_column(String(80), nullable=False)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    period_key: Mapped[str] = mapped_column(String(24), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_refresh_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analytics_refresh_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )


class AnalyticsPartitionWindow(Base, TimestampMixin):
    __tablename__ = "analytics_partition_windows"
    __table_args__ = (
        UniqueConstraint("table_name", "partition_key", name="uq_analytics_partition_window"),
        Index("ix_analytics_partition_table_start", "table_name", "range_start"),
        Index("ix_analytics_partition_status_start", "status", "range_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    table_name: Mapped[str] = mapped_column(String(120), nullable=False)
    partition_key: Mapped[str] = mapped_column(String(32), nullable=False)
    backend: Mapped[str] = mapped_column(String(24), nullable=False, default="logical")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="planned")
    range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
