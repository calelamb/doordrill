from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class QuestionnaireQuestion(Base):
    __tablename__ = "questionnaire_questions"
    __table_args__ = (
        Index("ix_questionnaire_questions_active_category_order", "active", "category", "display_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    options: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    maps_to_config_field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    responses: Mapped[list["OrgQuestionnaireResponse"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
    )


class OrgQuestionnaireResponse(Base):
    __tablename__ = "org_questionnaire_responses"
    __table_args__ = (
        UniqueConstraint("org_id", "question_id", name="uq_org_questionnaire_response"),
        Index("ix_org_questionnaire_responses_org_answered", "org_id", "answered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questionnaire_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_value: Mapped[str] = mapped_column(Text, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    question: Mapped["QuestionnaireQuestion"] = relationship(back_populates="responses")
