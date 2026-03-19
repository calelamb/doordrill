from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgPromptConfig(Base):
    __tablename__ = "org_prompt_configs"
    __table_args__ = (
        Index("ix_org_prompt_configs_org_published", "org_id", "published"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    company_name: Mapped[str] = mapped_column(String, nullable=False)
    product_category: Mapped[str] = mapped_column(String, nullable=False)
    product_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    pitch_stages: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    unique_selling_points: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    known_objections: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    target_demographics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    competitors: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)

    pricing_framing: Mapped[str | None] = mapped_column(Text, nullable=True)
    close_style: Mapped[str | None] = mapped_column(String, nullable=True)
    rep_tone_guidance: Mapped[str | None] = mapped_column(String, nullable=True)

    grading_priorities: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)

    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
