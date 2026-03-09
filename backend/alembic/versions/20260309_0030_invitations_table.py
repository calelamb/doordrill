"""add invitations table

Revision ID: 20260309_0030
Revises: 20260309_0029
Create Date: 2026-03-09 15:25:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260309_0030"
down_revision = "20260309_0029"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(index.get("name") == name for index in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "invitations"):
        op.create_table(
            "invitations",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("team_id", sa.String(length=36), nullable=True),
            sa.Column("invited_by", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="rep"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("token", name="uq_invitations_token"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "invitations") and not _has_index(inspector, "invitations", "ix_invitations_email_status"):
        op.create_index("ix_invitations_email_status", "invitations", ["email", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "invitations") and _has_index(inspector, "invitations", "ix_invitations_email_status"):
        op.drop_index("ix_invitations_email_status", table_name="invitations")

    if _has_table(inspector, "invitations"):
        op.drop_table("invitations")
