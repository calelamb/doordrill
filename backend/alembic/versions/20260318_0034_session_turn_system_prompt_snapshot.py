"""add system prompt snapshot to session turns

Revision ID: 20260318_0034
Revises: 20260310_0033
Create Date: 2026-03-18 10:34:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260318_0034"
down_revision = "20260310_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("session_turns")}
    if "system_prompt_snapshot" not in columns:
        op.add_column("session_turns", sa.Column("system_prompt_snapshot", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("session_turns")}
    if "system_prompt_snapshot" in columns:
        op.drop_column("session_turns", "system_prompt_snapshot")
