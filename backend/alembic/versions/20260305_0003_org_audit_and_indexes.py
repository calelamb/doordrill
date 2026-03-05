"""add org scoping, manager action logs, and performance indexes

Revision ID: 20260305_0003
Revises: 20260305_0002
Create Date: 2026-03-05 01:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0003"
down_revision = "20260305_0002"
branch_labels = None
depends_on = None


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def _has_unique(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(c.get("name") == name for c in inspector.get_unique_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "manager_action_logs" not in inspector.get_table_names():
        op.create_table(
            "manager_action_logs",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("manager_id", sa.String(length=36), nullable=False),
            sa.Column("action_type", sa.String(length=80), nullable=False),
            sa.Column("target_type", sa.String(length=80), nullable=False),
            sa.Column("target_id", sa.String(length=36), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE"),
        )

    scenario_columns = {column["name"] for column in inspector.get_columns("scenarios")}
    if "org_id" not in scenario_columns:
        with op.batch_alter_table("scenarios") as batch:
            batch.add_column(sa.Column("org_id", sa.String(length=36), nullable=True))

    inspector = sa.inspect(bind)

    if not _has_index(inspector, "manager_action_logs", "ix_manager_action_manager_ts"):
        op.create_index("ix_manager_action_manager_ts", "manager_action_logs", ["manager_id", "occurred_at"])

    if not _has_index(inspector, "sessions", "ix_sessions_assignment_started"):
        op.create_index("ix_sessions_assignment_started", "sessions", ["assignment_id", "started_at"])

    if not _has_index(inspector, "assignments", "ix_assignments_manager_status"):
        op.create_index("ix_assignments_manager_status", "assignments", ["assigned_by", "status"])

    if not _has_index(inspector, "session_events", "ix_session_events_session_ts"):
        op.create_index("ix_session_events_session_ts", "session_events", ["session_id", "event_ts"])

    if not _has_index(inspector, "session_artifacts", "ix_session_artifacts_session_type"):
        op.create_index("ix_session_artifacts_session_type", "session_artifacts", ["session_id", "artifact_type"])

    if not _has_unique(inspector, "session_turns", "uq_session_turns_session_turn_idx"):
        with op.batch_alter_table("session_turns") as batch:
            batch.create_unique_constraint("uq_session_turns_session_turn_idx", ["session_id", "turn_index"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_unique(inspector, "session_turns", "uq_session_turns_session_turn_idx"):
        with op.batch_alter_table("session_turns") as batch:
            batch.drop_constraint("uq_session_turns_session_turn_idx", type_="unique")

    for table, index in [
        ("session_artifacts", "ix_session_artifacts_session_type"),
        ("session_events", "ix_session_events_session_ts"),
        ("sessions", "ix_sessions_assignment_started"),
        ("assignments", "ix_assignments_manager_status"),
        ("manager_action_logs", "ix_manager_action_manager_ts"),
    ]:
        if table in inspector.get_table_names() and _has_index(inspector, table, index):
            op.drop_index(index, table_name=table)

    if "scenarios" in inspector.get_table_names():
        scenario_columns = {column["name"] for column in inspector.get_columns("scenarios")}
        if "org_id" in scenario_columns:
            with op.batch_alter_table("scenarios") as batch:
                batch.drop_column("org_id")

    if "manager_action_logs" in inspector.get_table_names():
        op.drop_table("manager_action_logs")
