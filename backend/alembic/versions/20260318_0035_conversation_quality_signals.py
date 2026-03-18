"""add conversation quality signals table

Revision ID: 20260318_0035
Revises: 20260318_0034
Create Date: 2026-03-18 10:35:00
"""

from __future__ import annotations

from alembic import op

from app.models.training import ConversationQualitySignal

# revision identifiers, used by Alembic.
revision = "20260318_0035"
down_revision = "20260318_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ConversationQualitySignal.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    ConversationQualitySignal.__table__.drop(bind, checkfirst=True)
