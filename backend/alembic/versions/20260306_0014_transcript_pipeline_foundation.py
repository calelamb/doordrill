"""add transcript enrichment columns and transcript fact tables

Revision ID: 20260306_0014
Revises: 20260306_0013
Create Date: 2026-03-06 18:45:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.models.transcript import FactTurnEvent, ObjectionType
from app.services.objection_taxonomy_service import CANONICAL_OBJECTION_TYPES

# revision identifiers, used by Alembic.
revision = "20260306_0014"
down_revision = "20260306_0013"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspector.get_columns(table))


TURN_COLUMNS: list[sa.Column] = [
    sa.Column("emotion_before", sa.String(length=32), nullable=True),
    sa.Column("emotion_after", sa.String(length=32), nullable=True),
    sa.Column("emotion_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("resistance_level", sa.Integer(), nullable=True),
    sa.Column("objection_pressure", sa.Integer(), nullable=True),
    sa.Column("active_objections", sa.JSON(), nullable=True),
    sa.Column("queued_objections", sa.JSON(), nullable=True),
    sa.Column("mb_tone", sa.String(length=32), nullable=True),
    sa.Column("mb_sentence_length", sa.String(length=16), nullable=True),
    sa.Column("mb_behaviors", sa.JSON(), nullable=True),
    sa.Column("mb_interruption_type", sa.String(length=32), nullable=True),
    sa.Column("mb_realism_score", sa.Float(), nullable=True),
    sa.Column("mb_opening_pause_ms", sa.Integer(), nullable=True),
    sa.Column("mb_total_pause_ms", sa.Integer(), nullable=True),
    sa.Column("behavioral_signals", sa.JSON(), nullable=True),
    sa.Column("was_graded", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("evidence_for_categories", sa.JSON(), nullable=True),
    sa.Column("is_high_quality", sa.Boolean(), nullable=True),
]


TABLES = [
    ObjectionType.__table__,
    FactTurnEvent.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "session_turns"):
        for column in TURN_COLUMNS:
            inspector = sa.inspect(bind)
            if _has_column(inspector, "session_turns", column.name):
                continue
            with op.batch_alter_table("session_turns") as batch_op:
                batch_op.add_column(column.copy())

    for table in TABLES:
        table.create(bind, checkfirst=True)

    session = Session(bind=bind)
    try:
        for seed in CANONICAL_OBJECTION_TYPES:
            row = session.scalar(
                sa.select(ObjectionType).where(
                    ObjectionType.org_id.is_(None),
                    ObjectionType.tag == seed.tag,
                )
            )
            if row is None:
                session.add(
                    ObjectionType(
                        org_id=None,
                        tag=seed.tag,
                        display_name=seed.display_name,
                        category=seed.category,
                        difficulty_weight=seed.difficulty_weight,
                        industry=seed.industry,
                        typical_phrases=list(seed.typical_phrases),
                        resolution_techniques=list(seed.resolution_techniques),
                        version=seed.version,
                        active=True,
                    )
                )
                continue

            row.display_name = seed.display_name
            row.category = seed.category
            row.difficulty_weight = seed.difficulty_weight
            row.industry = seed.industry
            row.typical_phrases = list(seed.typical_phrases)
            row.resolution_techniques = list(seed.resolution_techniques)
            row.version = seed.version
            row.active = True
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)

    if _has_table(inspector, "session_turns"):
        for column in reversed(TURN_COLUMNS):
            inspector = sa.inspect(bind)
            if not _has_column(inspector, "session_turns", column.name):
                continue
            with op.batch_alter_table("session_turns") as batch_op:
                batch_op.drop_column(column.name)
