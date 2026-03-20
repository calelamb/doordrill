"""add universal knowledge chunks table

Revision ID: 20260320_0040
Revises: 20260319_0039
Create Date: 2026-03-20 01:35:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260320_0040"
down_revision = "20260319_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "universal_knowledge_chunks" not in inspector.get_table_names():
        if bind.dialect.name == "postgresql":
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
            op.execute(
                """
                CREATE TABLE universal_knowledge_chunks (
                    id          SERIAL PRIMARY KEY,
                    category    VARCHAR(64)  NOT NULL,
                    content     TEXT         NOT NULL,
                    source_tag  VARCHAR(128) NOT NULL,
                    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
                    embedding   vector(1536),
                    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                )
                """
            )
        else:
            op.create_table(
                "universal_knowledge_chunks",
                sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
                sa.Column("category", sa.String(length=64), nullable=False),
                sa.Column("content", sa.Text(), nullable=False),
                sa.Column("source_tag", sa.String(length=128), nullable=False),
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
                sa.Column("embedding", sa.JSON(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            )

    # Refresh inspector after table creation
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("universal_knowledge_chunks")}

    if "ix_universal_knowledge_chunks_category" not in indexes:
        op.create_index("ix_universal_knowledge_chunks_category", "universal_knowledge_chunks", ["category"])
    if "ix_universal_knowledge_chunks_active" not in indexes:
        op.create_index("ix_universal_knowledge_chunks_active", "universal_knowledge_chunks", ["is_active"])

    if bind.dialect.name == "postgresql":
        # Only create HNSW index if embedding column is actually vector type
        col_type_row = bind.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'universal_knowledge_chunks' AND column_name = 'embedding'"
            )
        ).fetchone()
        col_type = col_type_row[0] if col_type_row else ""
        if "USER-DEFINED" in col_type or col_type == "USER-DEFINED":
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_universal_knowledge_chunks_embedding_hnsw "
                "ON universal_knowledge_chunks USING hnsw (embedding vector_cosine_ops) "
                "WITH (m=16, ef_construction=200)"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_universal_knowledge_chunks_embedding_hnsw")

    op.drop_index("ix_universal_knowledge_chunks_active", table_name="universal_knowledge_chunks")
    op.drop_index("ix_universal_knowledge_chunks_category", table_name="universal_knowledge_chunks")
    op.drop_table("universal_knowledge_chunks")
