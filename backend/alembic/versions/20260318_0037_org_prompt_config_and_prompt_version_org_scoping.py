"""add org prompt configs and org-scoped prompt versions

Revision ID: 20260318_0037
Revises: 20260318_0036
Create Date: 2026-03-18 15:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "20260318_0037"
down_revision = "20260318_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.create_index("ix_org_prompt_configs_org_id", "org_prompt_configs", ["org_id"], unique=True)
    op.create_index("ix_org_prompt_configs_org_published", "org_prompt_configs", ["org_id", "published"], unique=False)

    with op.batch_alter_table("prompt_versions") as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.String(), nullable=True))
        batch_op.drop_constraint("uq_prompt_versions_type_version", type_="unique")
        batch_op.drop_index("ix_prompt_versions_type_active")
        batch_op.create_unique_constraint(
            "uq_prompt_version_type_version_org",
            ["prompt_type", "version", "org_id"],
        )
        batch_op.create_index("ix_prompt_version_type_active_org", ["prompt_type", "active", "org_id"], unique=False)
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
