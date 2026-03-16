"""add password reset tokens table

Revision ID: 20260310_0033
Revises: 20260310_0032
Create Date: 2026-03-10 00:33:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260310_0033"
down_revision = "20260310_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "password_reset_tokens" not in inspector.get_table_names():
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token", sa.String(length=64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    inspector = sa.inspect(bind)
    index_names = {index["name"] for index in inspector.get_indexes("password_reset_tokens")}
    if "ix_prt_token" not in index_names and "ix_password_reset_tokens_token" not in index_names:
        op.create_index("ix_prt_token", "password_reset_tokens", ["token"], unique=True)
    if "ix_prt_user_id" not in index_names and "ix_password_reset_tokens_user_id" not in index_names:
        op.create_index("ix_prt_user_id", "password_reset_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_prt_user_id", table_name="password_reset_tokens")
    op.drop_index("ix_prt_token", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
