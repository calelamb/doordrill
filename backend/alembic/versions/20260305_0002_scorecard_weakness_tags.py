"""add weakness tags to scorecards

Revision ID: 20260305_0002
Revises: 20260305_0001
Create Date: 2026-03-05 00:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0002"
down_revision = "20260305_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("scorecards")}
    if "weakness_tags" not in existing:
        op.add_column("scorecards", sa.Column("weakness_tags", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("scorecards")}
    if "weakness_tags" in existing:
        op.drop_column("scorecards", "weakness_tags")
