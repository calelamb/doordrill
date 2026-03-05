import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import ReviewReason

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.user import User


def _uuid() -> str:
    return str(uuid.uuid4())


class Scorecard(Base, TimestampMixin):
    __tablename__ = "scorecards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    overall_score: Mapped[float] = mapped_column(nullable=False)
    category_scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    highlights: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_turn_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    weakness_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    session: Mapped["Session"] = relationship(back_populates="scorecard")
    reviews: Mapped[list["ManagerReview"]] = relationship(back_populates="scorecard", cascade="all, delete-orphan")
    coaching_notes: Mapped[list["ManagerCoachingNote"]] = relationship(
        back_populates="scorecard",
        cascade="all, delete-orphan",
        order_by=lambda: ManagerCoachingNote.created_at.desc(),
    )


class ManagerReview(Base):
    __tablename__ = "manager_reviews"
    __table_args__ = (
        Index("ix_manager_reviews_scorecard_reviewed_at", "scorecard_id", "reviewed_at"),
        Index(
            "uq_manager_reviews_scorecard_idempotency_key",
            "scorecard_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scorecard_id: Mapped[str] = mapped_column(ForeignKey("scorecards.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[ReviewReason] = mapped_column(Enum(ReviewReason), nullable=False)
    override_score: Mapped[float | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    scorecard: Mapped[Scorecard] = relationship(back_populates="reviews")
    reviewer: Mapped["User"] = relationship(back_populates="manager_reviews")


class ManagerCoachingNote(Base, TimestampMixin):
    __tablename__ = "manager_coaching_notes"
    __table_args__ = (
        Index("ix_manager_coaching_notes_scorecard_created", "scorecard_id", "created_at"),
        Index("ix_manager_coaching_notes_reviewer_created", "reviewer_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scorecard_id: Mapped[str] = mapped_column(ForeignKey("scorecards.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    visible_to_rep: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weakness_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    scorecard: Mapped[Scorecard] = relationship(back_populates="coaching_notes")
    reviewer: Mapped["User"] = relationship(back_populates="coaching_notes")
