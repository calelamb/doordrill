"""add adaptive recommendation outcomes

Revision ID: 20260308_0020
Revises: 20260308_0019
Create Date: 2026-03-08 13:00:00
"""

from __future__ import annotations

from alembic import op

from app.models.training import AdaptiveRecommendationOutcome

# revision identifiers, used by Alembic.
revision = "20260308_0020"
down_revision = "20260308_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    AdaptiveRecommendationOutcome.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    AdaptiveRecommendationOutcome.__table__.drop(bind, checkfirst=True)
