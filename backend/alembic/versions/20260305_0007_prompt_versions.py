"""add prompt version storage

Revision ID: 20260305_0007
Revises: 20260305_0006
Create Date: 2026-03-05 12:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0007"
down_revision = "20260305_0006"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(item.get("name") == column for item in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(item.get("name") == name for item in inspector.get_indexes(table))


def _has_unique(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(item.get("name") == name for item in inspector.get_unique_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "sessions") and not _has_column(inspector, "sessions", "prompt_version"):
        with op.batch_alter_table("sessions") as batch:
            batch.add_column(sa.Column("prompt_version", sa.String(length=64), nullable=True))

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "prompt_versions"):
        op.create_table(
            "prompt_versions",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("prompt_type", sa.String(length=64), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("prompt_type", "version", name="uq_prompt_versions_type_version"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "prompt_versions") and not _has_index(
        inspector, "prompt_versions", "ix_prompt_versions_type_active"
    ):
        op.create_index("ix_prompt_versions_type_active", "prompt_versions", ["prompt_type", "active"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "prompt_versions") and _has_index(
        inspector, "prompt_versions", "ix_prompt_versions_type_active"
    ):
        op.drop_index("ix_prompt_versions_type_active", table_name="prompt_versions")

    if _has_table(inspector, "prompt_versions") and _has_unique(
        inspector, "prompt_versions", "uq_prompt_versions_type_version"
    ):
        with op.batch_alter_table("prompt_versions") as batch:
            batch.drop_constraint("uq_prompt_versions_type_version", type_="unique")

    if _has_table(inspector, "prompt_versions"):
        op.drop_table("prompt_versions")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "sessions") and _has_column(inspector, "sessions", "prompt_version"):
        with op.batch_alter_table("sessions") as batch:
            batch.drop_column("prompt_version")
