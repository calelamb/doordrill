"""add prompt experiments for grading prompt routing

Revision ID: 20260308_0019
Revises: 20260308_0018
Create Date: 2026-03-08 12:20:00
"""

from __future__ import annotations

from alembic import op

from app.models.training import PromptExperiment

# revision identifiers, used by Alembic.
revision = "20260308_0019"
down_revision = "20260308_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    PromptExperiment.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    PromptExperiment.__table__.drop(bind, checkfirst=True)
