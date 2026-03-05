import uuid

from sqlalchemy import Boolean, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class PromptVersion(Base, TimestampMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_type", "version", name="uq_prompt_versions_type_version"),
        Index("ix_prompt_versions_type_active", "prompt_type", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prompt_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
