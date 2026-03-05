"""add review idempotency and coaching notes

Revision ID: 20260305_0008
Revises: 20260305_0007
Create Date: 2026-03-05 16:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0008"
down_revision = "20260305_0007"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE reviewreason ADD VALUE IF NOT EXISTS 'review_only'")

    if _has_table(inspector, "manager_reviews") and not _has_column(inspector, "manager_reviews", "idempotency_key"):
        op.add_column("manager_reviews", sa.Column("idempotency_key", sa.String(length=128), nullable=True))

    inspector = sa.inspect(bind)
    if _has_table(inspector, "manager_reviews") and not _has_index(
        inspector,
        "manager_reviews",
        "ix_manager_reviews_scorecard_reviewed_at",
    ):
        op.create_index(
            "ix_manager_reviews_scorecard_reviewed_at",
            "manager_reviews",
            ["scorecard_id", "reviewed_at"],
        )

    if _has_table(inspector, "manager_reviews") and not _has_index(
        inspector,
        "manager_reviews",
        "uq_manager_reviews_scorecard_idempotency_key",
    ):
        op.create_index(
            "uq_manager_reviews_scorecard_idempotency_key",
            "manager_reviews",
            ["scorecard_id", "idempotency_key"],
            unique=True,
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "manager_coaching_notes"):
        op.create_table(
            "manager_coaching_notes",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("scorecard_id", sa.String(length=36), nullable=False),
            sa.Column("reviewer_id", sa.String(length=36), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("visible_to_rep", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("weakness_tags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["scorecard_id"], ["scorecards.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="CASCADE"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "manager_coaching_notes") and not _has_index(
        inspector,
        "manager_coaching_notes",
        "ix_manager_coaching_notes_scorecard_created",
    ):
        op.create_index(
            "ix_manager_coaching_notes_scorecard_created",
            "manager_coaching_notes",
            ["scorecard_id", "created_at"],
        )
    if _has_table(inspector, "manager_coaching_notes") and not _has_index(
        inspector,
        "manager_coaching_notes",
        "ix_manager_coaching_notes_reviewer_created",
    ):
        op.create_index(
            "ix_manager_coaching_notes_reviewer_created",
            "manager_coaching_notes",
            ["reviewer_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "manager_coaching_notes") and _has_index(
        inspector, "manager_coaching_notes", "ix_manager_coaching_notes_reviewer_created"
    ):
        op.drop_index("ix_manager_coaching_notes_reviewer_created", table_name="manager_coaching_notes")
    if _has_table(inspector, "manager_coaching_notes") and _has_index(
        inspector, "manager_coaching_notes", "ix_manager_coaching_notes_scorecard_created"
    ):
        op.drop_index("ix_manager_coaching_notes_scorecard_created", table_name="manager_coaching_notes")
    if _has_table(inspector, "manager_coaching_notes"):
        op.drop_table("manager_coaching_notes")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "manager_reviews") and _has_index(
        inspector, "manager_reviews", "uq_manager_reviews_scorecard_idempotency_key"
    ):
        op.drop_index("uq_manager_reviews_scorecard_idempotency_key", table_name="manager_reviews")
    if _has_table(inspector, "manager_reviews") and _has_index(
        inspector, "manager_reviews", "ix_manager_reviews_scorecard_reviewed_at"
    ):
        op.drop_index("ix_manager_reviews_scorecard_reviewed_at", table_name="manager_reviews")
    if _has_table(inspector, "manager_reviews") and _has_column(inspector, "manager_reviews", "idempotency_key"):
        op.drop_column("manager_reviews", "idempotency_key")
