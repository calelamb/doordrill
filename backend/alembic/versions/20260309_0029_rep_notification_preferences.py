"""add rep notification preferences to users

Revision ID: 20260309_0029
Revises: 20260309_0028
Create Date: 2026-03-09 13:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "20260309_0029"
down_revision = "20260309_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "notification_preferences" in existing_columns:
        return

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("notification_preferences", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "notification_preferences" not in existing_columns:
        return

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("notification_preferences")
