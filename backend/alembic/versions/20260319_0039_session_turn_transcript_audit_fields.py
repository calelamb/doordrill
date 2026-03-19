"""add transcript audit fields to session turns

Revision ID: 20260319_0039
Revises: 20260318_0038
Create Date: 2026-03-19 09:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260319_0039"
down_revision = "20260318_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("session_turns")}

    if "raw_transcript_text" not in columns:
        op.add_column("session_turns", sa.Column("raw_transcript_text", sa.Text(), nullable=True))
    if "normalized_transcript_text" not in columns:
        op.add_column("session_turns", sa.Column("normalized_transcript_text", sa.Text(), nullable=True))
    if "transcript_provider" not in columns:
        op.add_column("session_turns", sa.Column("transcript_provider", sa.String(length=32), nullable=True))
    if "transcript_confidence" not in columns:
        op.add_column("session_turns", sa.Column("transcript_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("session_turns")}

    if "transcript_confidence" in columns:
        op.drop_column("session_turns", "transcript_confidence")
    if "transcript_provider" in columns:
        op.drop_column("session_turns", "transcript_provider")
    if "normalized_transcript_text" in columns:
        op.drop_column("session_turns", "normalized_transcript_text")
    if "raw_transcript_text" in columns:
        op.drop_column("session_turns", "raw_transcript_text")
