import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class FactTurnEvent(Base, TimestampMixin):
    __tablename__ = "fact_turn_events"
    __table_args__ = (
        Index("ix_fact_turn_events_session", "session_id"),
        Index("ix_fact_turn_events_rep_event_type", "rep_id", "event_type"),
        Index("ix_fact_turn_events_org_event_type_created", "org_id", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("session_turns.id", ondelete="CASCADE"), index=True, nullable=True)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(72), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    emotion_before: Mapped[str | None] = mapped_column(String(32), nullable=True)
    emotion_after: Mapped[str | None] = mapped_column(String(32), nullable=True)
    objection_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    objection_resolved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stage_before: Mapped[str | None] = mapped_column(String(72), nullable=True)
    stage_after: Mapped[str | None] = mapped_column(String(72), nullable=True)
    resistance_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pressure_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mb_realism_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ObjectionType(Base, TimestampMixin):
    __tablename__ = "objection_types"
    __table_args__ = (UniqueConstraint("org_id", "tag", name="uq_objection_type_org_tag"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True)
    tag: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    typical_phrases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    resolution_techniques: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
