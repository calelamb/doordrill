"""backfill objection taxonomy seed data

Revision ID: 20260308_0016
Revises: 20260307_0015
Create Date: 2026-03-08 09:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.models.transcript import ObjectionType
from app.services.objection_taxonomy_service import CANONICAL_OBJECTION_TYPES

# revision identifiers, used by Alembic.
revision = "20260308_0016"
down_revision = "20260307_0015"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "objection_types"):
        ObjectionType.__table__.create(bind, checkfirst=True)

    session = Session(bind=bind)
    try:
        for seed in CANONICAL_OBJECTION_TYPES:
            row = session.scalar(
                sa.select(ObjectionType).where(
                    ObjectionType.org_id.is_(None),
                    ObjectionType.tag == seed.tag,
                )
            )
            desired_phrases = list(seed.typical_phrases)
            desired_techniques = list(seed.resolution_techniques)

            if row is None:
                session.add(
                    ObjectionType(
                        org_id=None,
                        tag=seed.tag,
                        display_name=seed.display_name,
                        category=seed.category,
                        difficulty_weight=seed.difficulty_weight,
                        industry=seed.industry,
                        typical_phrases=desired_phrases,
                        resolution_techniques=desired_techniques,
                        version=seed.version,
                        active=True,
                    )
                )
                continue

            row.display_name = seed.display_name
            row.category = seed.category
            row.difficulty_weight = seed.difficulty_weight
            row.industry = seed.industry
            row.typical_phrases = desired_phrases
            row.resolution_techniques = desired_techniques
            row.version = seed.version
            row.active = True
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "objection_types"):
        return

    session = Session(bind=bind)
    try:
        session.execute(
            sa.delete(ObjectionType).where(
                ObjectionType.org_id.is_(None),
                ObjectionType.tag.in_([seed.tag for seed in CANONICAL_OBJECTION_TYPES]),
            )
        )
        session.commit()
    finally:
        session.close()
