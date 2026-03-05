"""add feed and replay performance indexes

Revision ID: 20260305_0010
Revises: 20260305_0009
Create Date: 2026-03-05 18:05:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0010"
down_revision = "20260305_0009"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = [
        ("sessions", "ix_sessions_rep_started", ["rep_id", "started_at"]),
        ("sessions", "ix_sessions_status_started", ["status", "started_at"]),
        ("sessions", "ix_sessions_scenario_started", ["scenario_id", "started_at"]),
        ("session_turns", "ix_session_turns_session_started", ["session_id", "started_at"]),
        ("session_turns", "ix_session_turns_session_speaker_started", ["session_id", "speaker", "started_at"]),
        ("session_events", "ix_session_events_session_type_ts", ["session_id", "event_type", "event_ts"]),
        ("assignments", "ix_assignments_assigned_by_created", ["assigned_by", "created_at"]),
        ("assignments", "ix_assignments_rep_status_due", ["rep_id", "status", "due_at"]),
    ]

    for table, name, columns in indexes:
        if _has_table(inspector, table) and not _has_index(inspector, table, name):
            op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, name in [
        ("assignments", "ix_assignments_rep_status_due"),
        ("assignments", "ix_assignments_assigned_by_created"),
        ("session_events", "ix_session_events_session_type_ts"),
        ("session_turns", "ix_session_turns_session_speaker_started"),
        ("session_turns", "ix_session_turns_session_started"),
        ("sessions", "ix_sessions_scenario_started"),
        ("sessions", "ix_sessions_status_started"),
        ("sessions", "ix_sessions_rep_started"),
    ]:
        if _has_table(inspector, table) and _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)
