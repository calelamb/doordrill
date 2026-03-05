"""harden notification retries and device token providers

Revision ID: 20260305_0009
Revises: 20260305_0008
Create Date: 2026-03-05 17:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0009"
down_revision = "20260305_0008"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "device_tokens") and not _has_column(inspector, "device_tokens", "provider"):
        op.add_column(
            "device_tokens",
            sa.Column("provider", sa.String(length=24), nullable=False, server_default="expo"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "device_tokens") and not _has_index(
        inspector,
        "device_tokens",
        "uq_device_tokens_user_provider_token",
    ):
        op.create_index(
            "uq_device_tokens_user_provider_token",
            "device_tokens",
            ["user_id", "provider", "token"],
            unique=True,
        )

    if _has_table(inspector, "notification_deliveries") and not _has_index(
        inspector,
        "notification_deliveries",
        "ix_notification_deliveries_status_next_retry",
    ):
        op.create_index(
            "ix_notification_deliveries_status_next_retry",
            "notification_deliveries",
            ["status", "next_retry_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "notification_deliveries") and _has_index(
        inspector,
        "notification_deliveries",
        "ix_notification_deliveries_status_next_retry",
    ):
        op.drop_index("ix_notification_deliveries_status_next_retry", table_name="notification_deliveries")

    if _has_table(inspector, "device_tokens") and _has_index(
        inspector,
        "device_tokens",
        "uq_device_tokens_user_provider_token",
    ):
        op.drop_index("uq_device_tokens_user_provider_token", table_name="device_tokens")

    if _has_table(inspector, "device_tokens") and _has_column(inspector, "device_tokens", "provider"):
        op.drop_column("device_tokens", "provider")
