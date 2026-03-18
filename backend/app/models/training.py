import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class OverrideLabel(Base, TimestampMixin):
    __tablename__ = "override_labels"
    __table_args__ = (
        Index("ix_override_labels_grading_run", "grading_run_id"),
        Index("ix_override_labels_manager_created", "manager_id", "created_at"),
        Index("ix_override_labels_exported", "exported_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    review_id: Mapped[str] = mapped_column(ForeignKey("manager_reviews.id", ondelete="CASCADE"), unique=True, nullable=False)
    grading_run_id: Mapped[str] = mapped_column(ForeignKey("grading_runs.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True)

    ai_overall_score: Mapped[float] = mapped_column(nullable=False)
    ai_category_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    override_overall_score: Mapped[float | None] = mapped_column(nullable=True)
    override_category_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    override_reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_delta_overall: Mapped[float] = mapped_column(nullable=False, default=0.0)
    is_high_disagreement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    label_quality: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PromptExperiment(Base, TimestampMixin):
    __tablename__ = "prompt_experiments"
    __table_args__ = (
        Index("ix_prompt_experiments_type_status", "prompt_type", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prompt_type: Mapped[str] = mapped_column(String(64), nullable=False)
    control_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_versions.id", ondelete="CASCADE"), nullable=False)
    challenger_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_versions.id", ondelete="CASCADE"), nullable=False)
    challenger_traffic_pct: Mapped[int] = mapped_column(nullable=False, default=10)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    winner: Mapped[str | None] = mapped_column(String(16), nullable=True)
    control_mean_calibration_error: Mapped[float | None] = mapped_column(nullable=True)
    challenger_mean_calibration_error: Mapped[float | None] = mapped_column(nullable=True)
    control_session_count: Mapped[int] = mapped_column(nullable=False, default=0)
    challenger_session_count: Mapped[int] = mapped_column(nullable=False, default=0)
    p_value: Mapped[float | None] = mapped_column(nullable=True)
    min_sessions_for_decision: Mapped[int] = mapped_column(nullable=False, default=200)


class ConversationQualitySignal(Base, TimestampMixin):
    __tablename__ = "conversation_quality_signals"
    __table_args__ = (
        Index("ix_conv_quality_signals_session", "session_id"),
        Index("ix_conv_quality_signals_manager_created", "manager_id", "created_at"),
        Index("ix_conv_quality_signals_exported", "exported_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manager_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    realism_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty_appropriate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    signal_responsiveness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged_turn_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AdaptiveRecommendationOutcome(Base, TimestampMixin):
    __tablename__ = "adaptive_recommendation_outcomes"
    __table_args__ = (
        Index("ix_adaptive_outcomes_rep_created", "rep_id", "created_at"),
        Index("ix_adaptive_outcomes_assignment", "assignment_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recommended_scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    recommended_difficulty: Mapped[int] = mapped_column(nullable=False, default=1)
    recommended_focus_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    baseline_skill_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    baseline_overall_score: Mapped[float | None] = mapped_column(nullable=True)
    outcome_skill_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    outcome_overall_score: Mapped[float | None] = mapped_column(nullable=True)
    skill_delta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    recommendation_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
