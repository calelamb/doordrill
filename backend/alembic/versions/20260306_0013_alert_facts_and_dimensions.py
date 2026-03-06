"""add analytics team/time dimensions and alert facts

Revision ID: 20260306_0013
Revises: 20260306_0012
Create Date: 2026-03-06 12:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.analytics import AnalyticsDimTeam, AnalyticsDimTime, AnalyticsFactAlert

# revision identifiers, used by Alembic.
revision = "20260306_0013"
down_revision = "20260306_0012"
branch_labels = None
depends_on = None


TABLES = [
    AnalyticsDimTeam.__table__,
    AnalyticsDimTime.__table__,
    AnalyticsFactAlert.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)

    with op.batch_alter_table("manager_action_logs") as batch_op:
        batch_op.alter_column(
            "target_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=160),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("manager_action_logs") as batch_op:
        batch_op.alter_column(
            "target_id",
            existing_type=sa.String(length=160),
            type_=sa.String(length=36),
            existing_nullable=False,
        )

    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
