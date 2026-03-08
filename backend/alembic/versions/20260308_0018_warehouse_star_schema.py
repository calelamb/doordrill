"""add warehouse star schema tables

Revision ID: 20260308_0018
Revises: 20260308_0017
Create Date: 2026-03-08 11:10:00
"""

from __future__ import annotations

from datetime import date, timedelta

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from app.models.warehouse import DimRep, DimScenario, DimTime, FactRepDaily, FactSession

# revision identifiers, used by Alembic.
revision = "20260308_0018"
down_revision = "20260308_0017"
branch_labels = None
depends_on = None


TABLES = [
    DimRep.__table__,
    DimScenario.__table__,
    DimTime.__table__,
    FactSession.__table__,
    FactRepDaily.__table__,
]


def _daterange(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)

    session = Session(bind=bind)
    try:
        existing = {
            row.date_key
            for row in session.scalars(
                sa.select(DimTime).where(
                    DimTime.date_key >= date(2025, 1, 1),
                    DimTime.date_key <= date(2030, 12, 31),
                )
            ).all()
        }
        for day_value in _daterange(date(2025, 1, 1), date(2030, 12, 31)):
            if day_value in existing:
                continue
            day_of_week = (day_value.weekday() + 1) % 7
            session.add(
                DimTime(
                    date_key=day_value,
                    day_of_week=day_of_week,
                    week_number=int(day_value.isocalendar().week),
                    month=day_value.month,
                    quarter=((day_value.month - 1) // 3) + 1,
                    year=day_value.year,
                    is_weekday=day_of_week not in {0, 6},
                )
            )
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
