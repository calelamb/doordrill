"""add org prompt configs and org-scoped prompt versions

Revision ID: 20260318_0037
Revises: 20260318_0036
Create Date: 2026-03-18 15:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision = "20260318_0037"
down_revision = "20260318_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_tables = inspector.get_table_names()
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("prompt_versions")}
    existing_columns = {col["name"] for col in inspector.get_columns("prompt_versions")}

    # Create org_prompt_configs only if it doesn't already exist
    if "org_prompt_configs" not in existing_tables:
        op.create_table(
            "org_prompt_configs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.String(), nullable=False),
            sa.Column("company_name", sa.String(), nullable=False),
            sa.Column("product_category", sa.String(), nullable=False),
            sa.Column("product_description", sa.Text(), nullable=True),
            sa.Column("pitch_stages", sa.JSON(), nullable=False),
            sa.Column("unique_selling_points", sa.JSON(), nullable=False),
            sa.Column("known_objections", sa.JSON(), nullable=False),
            sa.Column("target_demographics", sa.JSON(), nullable=False),
            sa.Column("competitors", sa.JSON(), nullable=False),
            sa.Column("pricing_framing", sa.Text(), nullable=True),
            sa.Column("close_style", sa.String(), nullable=True),
            sa.Column("rep_tone_guidance", sa.String(), nullable=True),
            sa.Column("grading_priorities", sa.JSON(), nullable=False),
            sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if "ix_org_prompt_configs_org_id" not in {idx["name"] for idx in inspector.get_indexes("org_prompt_configs")} if "org_prompt_configs" in existing_tables else set():
        op.create_index("ix_org_prompt_configs_org_id", "org_prompt_configs", ["org_id"], unique=True)
    if "ix_org_prompt_configs_org_published" not in {idx["name"] for idx in inspector.get_indexes("org_prompt_configs")} if "org_prompt_configs" in existing_tables else set():
        op.create_index("ix_org_prompt_configs_org_published", "org_prompt_configs", ["org_id", "published"], unique=False)

    # Always re-inspect after potential table creation
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("prompt_versions")}

    with op.batch_alter_table("prompt_versions") as batch_op:
        if "org_id" not in existing_columns:
            batch_op.add_column(sa.Column("org_id", sa.String(), nullable=True))
        if "uq_prompt_versions_type_version" in {c["name"] for c in inspector.get_unique_constraints("prompt_versions")}:
            batch_op.drop_constraint("uq_prompt_versions_type_version", type_="unique")
        if "ix_prompt_versions_type_active" in existing_indexes:
            batch_op.drop_index("ix_prompt_versions_type_active")
        if "uq_prompt_version_type_version_org" not in {c["name"] for c in inspector.get_unique_constraints("prompt_versions")}:
            batch_op.create_unique_constraint(
                "uq_prompt_version_type_version_org",
                ["prompt_type", "version", "org_id"],
            )
        if "ix_prompt_version_type_active_org" not in existing_indexes:
            batch_op.create_index("ix_prompt_version_type_active_org", ["prompt_type", "active", "org_id"], unique=False)
        if "ix_prompt_versions_org_id" not in existing_indexes:
            batch_op.create_index("ix_prompt_versions_org_id", ["org_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("prompt_versions") as batch_op:
        batch_op.drop_index("ix_prompt_versions_org_id")
        batch_op.drop_index("ix_prompt_version_type_active_org")
        batch_op.drop_constraint("uq_prompt_version_type_version_org", type_="unique")
        batch_op.create_unique_constraint("uq_prompt_versions_type_version", ["prompt_type", "version"])
        batch_op.create_index("ix_prompt_versions_type_active", ["prompt_type", "active"], unique=False)
        batch_op.drop_column("org_id")

    op.drop_index("ix_org_prompt_configs_org_published", table_name="org_prompt_configs")
    op.drop_index("ix_org_prompt_configs_org_id", table_name="org_prompt_configs")
    op.drop_table("org_prompt_configs")
