import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, Text
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

    session: Mapped["Session"] = relationship(back_populates="scorecard")
    reviews: Mapped[list["ManagerReview"]] = relationship(back_populates="scorecard", cascade="all, delete-orphan")


class ManagerReview(Base):
    __tablename__ = "manager_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scorecard_id: Mapped[str] = mapped_column(ForeignKey("scorecards.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_code: Mapped[ReviewReason] = mapped_column(Enum(ReviewReason), nullable=False)
    override_score: Mapped[float | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    scorecard: Mapped[Scorecard] = relationship(back_populates="reviews")
    reviewer: Mapped["User"] = relationship(back_populates="manager_reviews")
