"""add conversation quality fields to fact sessions

Revision ID: 20260318_0036
Revises: 20260318_0035
Create Date: 2026-03-18 10:36:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260318_0036"
down_revision = "20260318_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("fact_sessions")}
    if "has_conversation_quality_signal" not in columns:
        op.add_column("fact_sessions", sa.Column("has_conversation_quality_signal", sa.Boolean(), nullable=True))
    if "conversation_realism_rating" not in columns:
        op.add_column("fact_sessions", sa.Column("conversation_realism_rating", sa.Integer(), nullable=True))
    if "conversation_signal_responsiveness" not in columns:
        op.add_column("fact_sessions", sa.Column("conversation_signal_responsiveness", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("fact_sessions")}
    if "conversation_signal_responsiveness" in columns:
        op.drop_column("fact_sessions", "conversation_signal_responsiveness")
    if "conversation_realism_rating" in columns:
        op.drop_column("fact_sessions", "conversation_realism_rating")
    if "has_conversation_quality_signal" in columns:
        op.drop_column("fact_sessions", "has_conversation_quality_signal")
