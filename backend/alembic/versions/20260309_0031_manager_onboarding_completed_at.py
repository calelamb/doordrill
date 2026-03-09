"""add manager onboarding completed at

Revision ID: 20260309_0031
Revises: 20260309_0030
Create Date: 2026-03-09 20:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260309_0031"
down_revision = "20260309_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed_at")
