"""add rep risk scores

Revision ID: 20260308_0023
Revises: 20260308_0022
Create Date: 2026-03-08 16:00:00
"""

from __future__ import annotations

from alembic import op

from app.models.predictive import RepRiskScore

# revision identifiers, used by Alembic.
revision = "20260308_0023"
down_revision = "20260308_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    RepRiskScore.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RepRiskScore.__table__.drop(bind, checkfirst=True)
