"""add grading run audit table and scorecard v2 metadata

Revision ID: 20260307_0015
Revises: 20260306_0014
Create Date: 2026-03-07 09:15:00
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.models.prompt_version import PromptVersion
from app.services.grading_service import GradingPromptBuilder

# revision identifiers, used by Alembic.
revision = "20260307_0015"
down_revision = "20260306_0014"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(item.get("name") == name for item in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "scorecards") and not _has_column(inspector, "scorecards", "scorecard_schema_version"):
        with op.batch_alter_table("scorecards") as batch:
            batch.add_column(
                sa.Column(
                    "scorecard_schema_version",
                    sa.String(length=16),
                    nullable=False,
                    server_default="v1",
                )
            )

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "grading_runs"):
        op.create_table(
            "grading_runs",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("session_id", sa.String(length=36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scorecard_id", sa.String(length=36), sa.ForeignKey("scorecards.id", ondelete="SET NULL"), nullable=True),
            sa.Column("prompt_version_id", sa.String(length=36), sa.ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("model_name", sa.String(length=128), nullable=False),
            sa.Column("model_latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("input_token_count", sa.Integer(), nullable=True),
            sa.Column("output_token_count", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("raw_llm_response", sa.Text(), nullable=True),
            sa.Column("parse_error", sa.Text(), nullable=True),
            sa.Column("overall_score", sa.Float(), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "grading_runs") and not _has_index(inspector, "grading_runs", "ix_grading_runs_session_created"):
        op.create_index("ix_grading_runs_session_created", "grading_runs", ["session_id", "created_at"])
    inspector = sa.inspect(bind)
    if _has_table(inspector, "grading_runs") and not _has_index(inspector, "grading_runs", "ix_grading_runs_prompt_version_created"):
        op.create_index("ix_grading_runs_prompt_version_created", "grading_runs", ["prompt_version_id", "created_at"])

    session = Session(bind=bind)
    try:
        current = session.scalar(
            sa.select(PromptVersion).where(
                PromptVersion.prompt_type == "grading_v2",
                PromptVersion.version == "1.0.0",
            )
        )
        if current is None:
            current = PromptVersion(
                id=str(uuid.uuid4()),
                prompt_type="grading_v2",
                version="1.0.0",
                content=GradingPromptBuilder.template_blueprint(),
                active=True,
            )
            session.add(current)
        else:
            current.content = GradingPromptBuilder.template_blueprint()
            current.active = True
            current.updated_at = datetime.now(timezone.utc)

        for row in session.scalars(sa.select(PromptVersion).where(PromptVersion.prompt_type == "grading_v2")).all():
            row.active = row.version == "1.0.0"
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "prompt_versions"):
        session = Session(bind=bind)
        try:
            session.execute(
                sa.delete(PromptVersion).where(
                    PromptVersion.prompt_type == "grading_v2",
                    PromptVersion.version == "1.0.0",
                )
            )
            session.commit()
        finally:
            session.close()

    inspector = sa.inspect(bind)
    if _has_table(inspector, "grading_runs") and _has_index(inspector, "grading_runs", "ix_grading_runs_prompt_version_created"):
        op.drop_index("ix_grading_runs_prompt_version_created", table_name="grading_runs")
    inspector = sa.inspect(bind)
    if _has_table(inspector, "grading_runs") and _has_index(inspector, "grading_runs", "ix_grading_runs_session_created"):
        op.drop_index("ix_grading_runs_session_created", table_name="grading_runs")
    inspector = sa.inspect(bind)
    if _has_table(inspector, "grading_runs"):
        op.drop_table("grading_runs")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "scorecards") and _has_column(inspector, "scorecards", "scorecard_schema_version"):
        with op.batch_alter_table("scorecards") as batch:
            batch.drop_column("scorecard_schema_version")
