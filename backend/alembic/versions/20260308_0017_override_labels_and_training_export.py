"""add override labels for training exports

Revision ID: 20260308_0017
Revises: 20260308_0016
Create Date: 2026-03-08 10:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.training import OverrideLabel

# revision identifiers, used by Alembic.
revision = "20260308_0017"
down_revision = "20260308_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    OverrideLabel.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    OverrideLabel.__table__.drop(bind, checkfirst=True)
