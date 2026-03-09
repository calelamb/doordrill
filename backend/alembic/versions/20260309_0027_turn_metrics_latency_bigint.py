"""widen first response latency metric to bigint

Revision ID: 20260309_0027
Revises: 20260308_0026
Create Date: 2026-03-09 01:25:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260309_0027"
down_revision = "20260308_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("analytics_fact_session_turn_metrics") as batch_op:
        batch_op.alter_column(
            "first_response_latency_ms",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("analytics_fact_session_turn_metrics") as batch_op:
        batch_op.alter_column(
            "first_response_latency_ms",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
