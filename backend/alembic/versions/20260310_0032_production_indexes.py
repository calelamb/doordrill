"""add missing production indexes

Revision ID: 20260310_0032
Revises: 20260309_0031
Create Date: 2026-03-10 00:32:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260310_0032"
down_revision = "20260309_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_session_events_event_id_unique",
        "session_events",
        ["event_id"],
        unique=True,
        if_not_exists=True,
    )
    op.create_index(
        "ix_session_turns_session_turn_idx",
        "session_turns",
        ["session_id", "turn_index"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_assignments_rep_status",
        "assignments",
        ["rep_id", "status"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_assignments_rep_status", table_name="assignments")
    op.drop_index("ix_session_turns_session_turn_idx", table_name="session_turns")
    op.drop_index("ix_session_events_event_id_unique", table_name="session_events")
