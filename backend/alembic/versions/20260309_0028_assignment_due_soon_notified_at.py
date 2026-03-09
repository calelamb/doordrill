"""add due-soon notification marker to assignments

Revision ID: 20260309_0028
Revises: 20260309_0027
Create Date: 2026-03-09 10:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260309_0028"
down_revision = "20260309_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("assignments")}
    if "due_soon_notified_at" in existing_columns:
        return

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("due_soon_notified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("assignments")}
    if "due_soon_notified_at" not in existing_columns:
        return

    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_column("due_soon_notified_at")
