import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import EventDirection, SessionStatus, TurnSpeaker

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.scorecard import Scorecard
    from app.models.user import User


def _uuid() -> str:
    return str(uuid.uuid4())


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_assignment_started", "assignment_id", "started_at"),
        Index("ix_sessions_rep_started", "rep_id", "started_at"),
        Index("ix_sessions_status_started", "status", "started_at"),
        Index("ix_sessions_scenario_started", "scenario_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), nullable=False, default=SessionStatus.ACTIVE)

    assignment: Mapped["Assignment"] = relationship(back_populates="sessions")
    rep: Mapped["User"] = relationship(back_populates="sessions")
    events: Mapped[list["SessionEvent"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    turns: Mapped[list["SessionTurn"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    artifacts: Mapped[list["SessionArtifact"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    scorecard: Mapped["Scorecard | None"] = relationship(back_populates="session", uselist=False)


class SessionEvent(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_session_events_event_id"),
        Index("ix_session_events_session_ts", "session_id", "event_ts"),
        Index("ix_session_events_session_type_ts", "session_id", "event_type", "event_ts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(72), nullable=False)
    event_type: Mapped[str] = mapped_column(String(72), nullable=False)
    direction: Mapped[EventDirection] = mapped_column(Enum(EventDirection), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    session: Mapped[Session] = relationship(back_populates="events")


class SessionTurn(Base):
    __tablename__ = "session_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", name="uq_session_turns_session_turn_idx"),
        Index("ix_session_turns_session_started", "session_id", "started_at"),
        Index("ix_session_turns_session_speaker_started", "session_id", "speaker", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[TurnSpeaker] = mapped_column(Enum(TurnSpeaker), nullable=False)
    stage: Mapped[str] = mapped_column(String(72), nullable=False, default="objection_handling")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    objection_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    emotion_before: Mapped[str | None] = mapped_column(String(32), nullable=True)
    emotion_after: Mapped[str | None] = mapped_column(String(32), nullable=True)
    emotion_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resistance_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    objection_pressure: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_objections: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    queued_objections: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    mb_tone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mb_sentence_length: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mb_behaviors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    mb_interruption_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mb_realism_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    mb_opening_pause_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mb_total_pause_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    behavioral_signals: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    was_graded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_for_categories: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    is_high_quality: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    session: Mapped[Session] = relationship(back_populates="turns")


class SessionArtifact(Base, TimestampMixin):
    __tablename__ = "session_artifacts"
    __table_args__ = (Index("ix_session_artifacts_session_type", "session_id", "artifact_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    session: Mapped[Session] = relationship(back_populates="artifacts")
