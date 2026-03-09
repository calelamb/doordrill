"""add predictive skill forecasts

Revision ID: 20260308_0022
Revises: 20260308_0021
Create Date: 2026-03-08 15:15:00
"""

from __future__ import annotations

from alembic import op

from app.models.predictive import RepSkillForecast

# revision identifiers, used by Alembic.
revision = "20260308_0022"
down_revision = "20260308_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    RepSkillForecast.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RepSkillForecast.__table__.drop(bind, checkfirst=True)
