"""add manager onboarding completed at

Revision ID: 20260309_0031
Revises: 20260309_0030
Create Date: 2026-03-09 20:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260309_0031"
down_revision = "20260309_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "onboarding_completed_at" in existing_columns:
        return
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    if "onboarding_completed_at" not in existing_columns:
        return
    op.drop_column("users", "onboarding_completed_at")
