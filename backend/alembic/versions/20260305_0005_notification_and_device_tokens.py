"""add notification deliveries and device tokens

Revision ID: 20260305_0005
Revises: 20260305_0004
Create Date: 2026-03-05 09:05:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0005"
down_revision = "20260305_0004"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "device_tokens"):
        op.create_table(
            "device_tokens",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("platform", sa.String(length=24), nullable=False),
            sa.Column("token", sa.String(length=512), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )

    if not _has_table(inspector, "notification_deliveries"):
        op.create_table(
            "notification_deliveries",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("manager_id", sa.String(length=36), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("provider_response", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE"),
        )

    inspector = sa.inspect(bind)
    indexes = [
        ("device_tokens", "ix_device_tokens_user_platform", ["user_id", "platform"]),
        ("device_tokens", "ix_device_tokens_token", ["token"]),
        ("notification_deliveries", "ix_notification_deliveries_session_status", ["session_id", "status"]),
        ("notification_deliveries", "ix_notification_deliveries_manager_status", ["manager_id", "status"]),
    ]
    for table, name, columns in indexes:
        if _has_table(inspector, table) and not _has_index(inspector, table, name):
            op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, name in [
        ("notification_deliveries", "ix_notification_deliveries_manager_status"),
        ("notification_deliveries", "ix_notification_deliveries_session_status"),
        ("device_tokens", "ix_device_tokens_token"),
        ("device_tokens", "ix_device_tokens_user_platform"),
    ]:
        if _has_table(inspector, table) and _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)

    if _has_table(inspector, "notification_deliveries"):
        op.drop_table("notification_deliveries")
    if _has_table(inspector, "device_tokens"):
        op.drop_table("device_tokens")
