import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class DimRep(Base, TimestampMixin):
    __tablename__ = "dim_reps"
    __table_args__ = (
        Index("ix_dim_reps_org_team", "org_id", "team_id"),
        Index("ix_dim_reps_last_session", "last_session_at"),
    )

    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    rep_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hire_cohort: Mapped[date | None] = mapped_column(Date, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DimScenario(Base, TimestampMixin):
    __tablename__ = "dim_scenarios"
    __table_args__ = (
        Index("ix_dim_scenarios_org_industry", "org_id", "industry"),
    )

    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True)
    scenario_name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    objection_focus: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DimTime(Base, TimestampMixin):
    __tablename__ = "dim_time"
    __table_args__ = (
        Index("ix_dim_time_year_month", "year", "month"),
        Index("ix_dim_time_week_number", "year", "week_number"),
    )

    date_key: Mapped[date] = mapped_column(Date, primary_key=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    is_weekday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FactSession(Base, TimestampMixin):
    __tablename__ = "fact_sessions"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_fact_sessions_session_id"),
        Index("ix_fact_sessions_org_date", "org_id", "session_date"),
        Index("ix_fact_sessions_manager_date", "manager_id", "session_date"),
        Index("ix_fact_sessions_rep_date", "rep_id", "session_date"),
        Index("ix_fact_sessions_scenario_date", "scenario_id", "session_date"),
        Index("ix_fact_sessions_overall_score", "overall_score"),
    )

    fact_session_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_opening: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_pitch_delivery: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_objection_handling: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_closing_technique: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_professionalism: Mapped[float | None] = mapped_column(Float, nullable=True)
    grading_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_version_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True)

    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rep_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    barge_in_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_rep_turn_length_chars: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_emotion: Mapped[str | None] = mapped_column(String(32), nullable=True)

    has_manager_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    override_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_coaching_note: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    weakness_tag_1: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weakness_tag_2: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weakness_tag_3: Mapped[str | None] = mapped_column(String(64), nullable=True)

    etl_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    etl_written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FactRepDaily(Base, TimestampMixin):
    __tablename__ = "fact_rep_daily"
    __table_args__ = (
        UniqueConstraint("rep_id", "session_date", name="uq_fact_rep_daily_rep_date"),
        Index("ix_fact_rep_daily_org_date", "org_id", "session_date"),
        Index("ix_fact_rep_daily_manager_date", "manager_id", "session_date"),
        Index("ix_fact_rep_daily_rep_date", "rep_id", "session_date"),
    )

    fact_rep_daily_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_objection_handling: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_closing_technique: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    barge_in_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    override_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coaching_note_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
