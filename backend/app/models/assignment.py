import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import AssignmentStatus

if TYPE_CHECKING:
    from app.models.scenario import Scenario
    from app.models.session import Session
    from app.models.user import User


def _uuid() -> str:
    return str(uuid.uuid4())


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"
    __table_args__ = (Index("ix_assignments_manager_status", "assigned_by", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True, nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    assigned_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[AssignmentStatus] = mapped_column(Enum(AssignmentStatus), default=AssignmentStatus.ASSIGNED, nullable=False)
    min_score_target: Mapped[float | None] = mapped_column(nullable=True)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    scenario: Mapped["Scenario"] = relationship(back_populates="assignments")
    rep: Mapped["User"] = relationship(back_populates="assignments", foreign_keys=[rep_id])
    assigned_by_user: Mapped["User"] = relationship(back_populates="assigned_by", foreign_keys=[assigned_by])
    sessions: Mapped[list["Session"]] = relationship(back_populates="assignment")
