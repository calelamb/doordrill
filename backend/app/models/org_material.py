from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.models.base import Base

try:  # pragma: no cover - optional dependency in local/test
    from pgvector.sqlalchemy import Vector as PgVector
except Exception:  # pragma: no cover
    PgVector = None

if TYPE_CHECKING:
    from app.models.user import Organization


class Vector(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql" and PgVector is not None:
            return dialect.type_descriptor(PgVector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Dialect):
        if value is None:
            return None
        if dialect.name == "postgresql" and PgVector is not None:
            return value
        return [float(item) for item in value]

    def process_result_value(self, value: Any, dialect: Dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return [float(item) for item in value]
        return value


class OrgMaterial(Base):
    __tablename__ = "org_materials"
    __table_args__ = (
        Index("ix_org_materials_org_created", "org_id", "created_at"),
        Index("ix_org_materials_org_status", "org_id", "extraction_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
    knowledge_docs: Mapped[list["OrgKnowledgeDoc"]] = relationship(
        back_populates="material",
        cascade="all, delete-orphan",
        order_by="OrgKnowledgeDoc.id.asc()",
    )


class OrgKnowledgeDoc(Base):
    __tablename__ = "org_knowledge_docs"
    __table_args__ = (
        Index("ix_org_knowledge_docs_org", "org_id"),
        Index("ix_org_knowledge_docs_org_type_approved", "org_id", "extraction_type", "manager_approved"),
        Index("ix_org_knowledge_docs_material_type", "material_id", "extraction_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    material_id: Mapped[int] = mapped_column(
        ForeignKey("org_materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    extraction_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    manager_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    used_in_config: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    material: Mapped["OrgMaterial"] = relationship(back_populates="knowledge_docs")
