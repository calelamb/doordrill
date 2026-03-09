import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class RepSkillForecast(Base, TimestampMixin):
    __tablename__ = "rep_skill_forecasts"
    __table_args__ = (
        UniqueConstraint("rep_id", "skill", name="uq_rep_skill_forecast_rep_skill"),
        Index("ix_rep_skill_forecasts_rep", "rep_id"),
        Index("ix_rep_skill_forecasts_org", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    skill: Mapped[str] = mapped_column(String(64), nullable=False)
    current_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    sessions_to_readiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    projected_ready_at_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    readiness_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=7.0)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RepRiskScore(Base, TimestampMixin):
    __tablename__ = "rep_risk_scores"
    __table_args__ = (
        UniqueConstraint("rep_id", name="uq_rep_risk_score_rep"),
        Index("ix_rep_risk_scores_org_risk", "org_id", "risk_level"),
        Index("ix_rep_risk_scores_manager", "manager_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    is_plateauing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_declining: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_disengaging: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plateau_duration_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decline_slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_since_last_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_frequency_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_frequency_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_alerts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    suppressed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScenarioOutcomeAggregate(Base, TimestampMixin):
    __tablename__ = "scenario_outcome_aggregates"
    __table_args__ = (
        UniqueConstraint("scenario_id", "focus_skill", "difficulty_bucket", name="uq_scenario_outcome_agg"),
        Index("ix_scenario_outcome_agg_skill_difficulty", "focus_skill", "difficulty_bucket"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    focus_skill: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty_bucket: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_skill_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_outcome_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RepCohortBenchmark(Base, TimestampMixin):
    __tablename__ = "rep_cohort_benchmarks"
    __table_args__ = (
        UniqueConstraint("rep_id", "skill", name="uq_rep_cohort_benchmark_rep_skill"),
        Index("ix_rep_cohort_benchmarks_rep", "rep_id"),
        Index("ix_rep_cohort_benchmarks_org_cohort", "org_id", "cohort_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    skill: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_label: Mapped[str] = mapped_column(String(16), nullable=False)
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_p25: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_p50: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_p75: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_in_cohort: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_in_org: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ManagerCoachingImpact(Base, TimestampMixin):
    __tablename__ = "manager_coaching_impacts"
    __table_args__ = (
        Index("ix_manager_coaching_impact_manager", "manager_id"),
        Index("ix_manager_coaching_impact_rep", "rep_id"),
        Index("ix_manager_coaching_impact_session", "source_session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    source_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    intervention_type: Mapped[str] = mapped_column(String(32), nullable=False)
    intervention_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pre_intervention_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    post_intervention_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    sessions_observed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observation_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    impact_classified: Mapped[str | None] = mapped_column(String(16), nullable=True)
    impact_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
