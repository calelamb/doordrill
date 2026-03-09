"""add manager coaching impacts

Revision ID: 20260308_0026
Revises: 20260308_0025
Create Date: 2026-03-08 17:30:00
"""

from __future__ import annotations

from alembic import op

from app.models.predictive import ManagerCoachingImpact

# revision identifiers, used by Alembic.
revision = "20260308_0026"
down_revision = "20260308_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ManagerCoachingImpact.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    ManagerCoachingImpact.__table__.drop(bind, checkfirst=True)
