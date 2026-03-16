"""add org knowledge base documents

Revision ID: 20260308_0021
Revises: 20260308_0020
Create Date: 2026-03-08 14:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType


class VectorType(UserDefinedType):
    def get_col_spec(self, **kw):
        return "VECTOR(1536)"


# revision identifiers, used by Alembic.
revision = "20260308_0021"
down_revision = "20260308_0020"
branch_labels = None
depends_on = None


def _document_status_enum(bind):
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM(
            "pending",
            "processing",
            "ready",
            "failed",
            name="orgdocumentstatus",
            create_type=False,
        )
    return sa.Enum("pending", "processing", "ready", "failed", name="orgdocumentstatus")


def _document_file_type_enum(bind):
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM(
            "pdf",
            "docx",
            "txt",
            "video_transcript",
            name="orgdocumentfiletype",
            create_type=False,
        )
    return sa.Enum("pdf", "docx", "txt", "video_transcript", name="orgdocumentfiletype")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    status_enum = _document_status_enum(bind)
    file_type_enum = _document_file_type_enum(bind)

    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        status_enum.create(bind, checkfirst=True)
        file_type_enum.create(bind, checkfirst=True)

    if "org_documents" not in inspector.get_table_names():
        op.create_table(
            "org_documents",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("original_filename", sa.String(length=255), nullable=False),
            sa.Column("file_type", file_type_enum, nullable=False),
            sa.Column("storage_key", sa.String(length=600), nullable=False),
            sa.Column("status", status_enum, nullable=False),
            sa.Column("chunk_count", sa.Integer(), nullable=True),
            sa.Column("token_count", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("uploaded_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    inspector = sa.inspect(bind)
    org_document_indexes = {index["name"] for index in inspector.get_indexes("org_documents")}
    if "ix_org_documents_org_created" not in org_document_indexes:
        op.create_index("ix_org_documents_org_created", "org_documents", ["org_id", "created_at"])
    if "ix_org_documents_org_status" not in org_document_indexes:
        op.create_index("ix_org_documents_org_status", "org_documents", ["org_id", "status"])

    embedding_type = VectorType() if bind.dialect.name == "postgresql" else sa.JSON()
    if "org_document_chunks" not in inspector.get_table_names():
        op.create_table(
            "org_document_chunks",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("document_id", sa.String(length=36), sa.ForeignKey("org_documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False),
            sa.Column("embedding", embedding_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("document_id", "chunk_index", name="uq_org_document_chunks_doc_idx"),
        )

    inspector = sa.inspect(bind)
    chunk_indexes = {index["name"] for index in inspector.get_indexes("org_document_chunks")}
    if "ix_org_document_chunks_org_document" not in chunk_indexes:
        op.create_index("ix_org_document_chunks_org_document", "org_document_chunks", ["org_id", "document_id"])
    if "ix_org_document_chunks_document_idx" not in chunk_indexes:
        op.create_index("ix_org_document_chunks_document_idx", "org_document_chunks", ["document_id", "chunk_index"])

    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_org_document_chunks_embedding_hnsw "
            "ON org_document_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m=16, ef_construction=200)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_org_document_chunks_embedding_hnsw")

    op.drop_index("ix_org_document_chunks_document_idx", table_name="org_document_chunks")
    op.drop_index("ix_org_document_chunks_org_document", table_name="org_document_chunks")
    op.drop_table("org_document_chunks")

    op.drop_index("ix_org_documents_org_status", table_name="org_documents")
    op.drop_index("ix_org_documents_org_created", table_name="org_documents")
    op.drop_table("org_documents")

    if bind.dialect.name == "postgresql":
        _document_file_type_enum(bind).drop(bind, checkfirst=True)
        _document_status_enum(bind).drop(bind, checkfirst=True)
