from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.models.base import Base, TimestampMixin
from app.models.types import OrgDocumentFileType, OrgDocumentStatus

try:
    from pgvector.sqlalchemy import Vector as PgVector
except Exception:  # pragma: no cover - optional dependency
    PgVector = None

if TYPE_CHECKING:
    from app.models.user import Organization, User


def _uuid() -> str:
    return str(uuid.uuid4())


def _enum_values(enum_cls: type[PyEnum]) -> list[str]:
    return [str(item.value) for item in enum_cls]


class EmbeddingVector(TypeDecorator):
    """Use pgvector on Postgres when available, JSON elsewhere for local tests."""

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


class OrgDocument(Base, TimestampMixin):
    __tablename__ = "org_documents"
    __table_args__ = (
        Index("ix_org_documents_org_created", "org_id", "created_at"),
        Index("ix_org_documents_org_status", "org_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[OrgDocumentFileType] = mapped_column(
        Enum(OrgDocumentFileType, values_callable=_enum_values),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    status: Mapped[OrgDocumentStatus] = mapped_column(
        Enum(OrgDocumentStatus, values_callable=_enum_values),
        nullable=False,
        default=OrgDocumentStatus.PENDING,
    )
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    organization: Mapped["Organization"] = relationship()
    uploader: Mapped["User"] = relationship()
    chunks: Mapped[list["OrgDocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="OrgDocumentChunk.chunk_index",
    )


class OrgDocumentChunk(Base):
    __tablename__ = "org_document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_org_document_chunks_doc_idx"),
        Index("ix_org_document_chunks_org_document", "org_id", "document_id"),
        Index("ix_org_document_chunks_document_idx", "document_id", "chunk_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("org_documents.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingVector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    document: Mapped[OrgDocument] = relationship(back_populates="chunks")
