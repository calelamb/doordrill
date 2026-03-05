"""add local auth fields to users

Revision ID: 20260305_0004
Revises: 20260305_0003
Create Date: 2026-03-05 08:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260305_0004"
down_revision = "20260305_0003"
branch_labels = None
depends_on = None


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}

    with op.batch_alter_table("users") as batch:
        if "password_hash" not in user_columns:
            batch.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        if "auth_provider" not in user_columns:
            batch.add_column(sa.Column("auth_provider", sa.String(length=50), nullable=False, server_default="local"))

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "users", "ix_users_org_role"):
        op.create_index("ix_users_org_role", "users", ["org_id", "role"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "users", "ix_users_org_role"):
        op.drop_index("ix_users_org_role", table_name="users")

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "auth_provider" in user_columns:
            batch.drop_column("auth_provider")
        if "password_hash" in user_columns:
            batch.drop_column("password_hash")
