"""add rep cohort benchmarks

Revision ID: 20260308_0025
Revises: 20260308_0024
Create Date: 2026-03-08 17:00:00
"""

from __future__ import annotations

from alembic import op

from app.models.predictive import RepCohortBenchmark

# revision identifiers, used by Alembic.
revision = "20260308_0025"
down_revision = "20260308_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    RepCohortBenchmark.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RepCohortBenchmark.__table__.drop(bind, checkfirst=True)
