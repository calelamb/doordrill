"""add analytics materialized storage and partition metadata

Revision ID: 20260306_0012
Revises: 20260305_0011
Create Date: 2026-03-06 09:15:00
"""

from __future__ import annotations

from alembic import op

from app.models.analytics import AnalyticsMaterializedView, AnalyticsPartitionWindow

# revision identifiers, used by Alembic.
revision = "20260306_0012"
down_revision = "20260305_0011"
branch_labels = None
depends_on = None


TABLES = [
    AnalyticsMaterializedView.__table__,
    AnalyticsPartitionWindow.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
