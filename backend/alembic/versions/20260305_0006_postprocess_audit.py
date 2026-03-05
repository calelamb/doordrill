"""add postprocess run audit table

Revision ID: 20260305_0006
Revises: 20260305_0005
Create Date: 2026-03-05 09:12:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0006"
down_revision = "20260305_0005"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def _has_unique(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(item.get("name") == name for item in inspector.get_unique_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "postprocess_runs"):
        op.create_table(
            "postprocess_runs",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("task_type", sa.String(length=48), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("session_id", "task_type", name="uq_postprocess_runs_session_task"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "postprocess_runs") and not _has_index(
        inspector, "postprocess_runs", "ix_postprocess_runs_status_next_retry"
    ):
        op.create_index(
            "ix_postprocess_runs_status_next_retry",
            "postprocess_runs",
            ["status", "next_retry_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "postprocess_runs") and _has_index(
        inspector, "postprocess_runs", "ix_postprocess_runs_status_next_retry"
    ):
        op.drop_index("ix_postprocess_runs_status_next_retry", table_name="postprocess_runs")

    if _has_table(inspector, "postprocess_runs") and _has_unique(
        inspector, "postprocess_runs", "uq_postprocess_runs_session_task"
    ):
        with op.batch_alter_table("postprocess_runs") as batch:
            batch.drop_constraint("uq_postprocess_runs_session_task", type_="unique")

    if _has_table(inspector, "postprocess_runs"):
        op.drop_table("postprocess_runs")
