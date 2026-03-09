"""add scenario outcome aggregates

Revision ID: 20260308_0024
Revises: 20260308_0023
Create Date: 2026-03-08 16:30:00
"""

from __future__ import annotations

from alembic import op

from app.models.predictive import ScenarioOutcomeAggregate

# revision identifiers, used by Alembic.
revision = "20260308_0024"
down_revision = "20260308_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ScenarioOutcomeAggregate.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    ScenarioOutcomeAggregate.__table__.drop(bind, checkfirst=True)
