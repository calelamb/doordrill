import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True, nullable=False)
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
    __table_args__ = (UniqueConstraint("event_id", name="uq_session_events_event_id"),)

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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[TurnSpeaker] = mapped_column(Enum(TurnSpeaker), nullable=False)
    stage: Mapped[str] = mapped_column(String(72), nullable=False, default="objection_handling")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    objection_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    session: Mapped[Session] = relationship(back_populates="turns")


class SessionArtifact(Base, TimestampMixin):
    __tablename__ = "session_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    session: Mapped[Session] = relationship(back_populates="artifacts")
