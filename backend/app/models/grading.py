import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.prompt_version import PromptVersion
    from app.models.scorecard import Scorecard
    from app.models.session import Session


def _uuid() -> str:
    return str(uuid.uuid4())


class GradingRun(Base, TimestampMixin):
    """Auditable record for a single grading attempt."""

    __tablename__ = "grading_runs"
    __table_args__ = (
        Index("ix_grading_runs_session_created", "session_id", "created_at"),
        Index("ix_grading_runs_prompt_version_created", "prompt_version_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    scorecard_id: Mapped[str | None] = mapped_column(ForeignKey("scorecards.id", ondelete="SET NULL"), index=True, nullable=True)
    prompt_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    raw_llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    confidence_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["Session"] = relationship()
    scorecard: Mapped["Scorecard | None"] = relationship(back_populates="grading_runs")
    prompt_version: Mapped["PromptVersion"] = relationship()
