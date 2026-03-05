"""add analytics platform foundation tables

Revision ID: 20260305_0011
Revises: 20260305_0010
Create Date: 2026-03-05 23:45:00
"""

from __future__ import annotations

from alembic import op

from app.models.analytics import (
    AnalyticsDimManager,
    AnalyticsDimRep,
    AnalyticsDimScenario,
    AnalyticsFactCoachingIntervention,
    AnalyticsFactManagerCalibration,
    AnalyticsFactRepDay,
    AnalyticsFactRepWeek,
    AnalyticsFactScenarioDay,
    AnalyticsFactSession,
    AnalyticsFactSessionTurnMetrics,
    AnalyticsFactTeamDay,
    AnalyticsMetricDefinition,
    AnalyticsMetricSnapshot,
    AnalyticsRefreshRun,
)

# revision identifiers, used by Alembic.
revision = "20260305_0011"
down_revision = "20260305_0010"
branch_labels = None
depends_on = None


TABLES = [
    AnalyticsRefreshRun.__table__,
    AnalyticsMetricDefinition.__table__,
    AnalyticsMetricSnapshot.__table__,
    AnalyticsDimManager.__table__,
    AnalyticsDimRep.__table__,
    AnalyticsDimScenario.__table__,
    AnalyticsFactSession.__table__,
    AnalyticsFactSessionTurnMetrics.__table__,
    AnalyticsFactRepDay.__table__,
    AnalyticsFactRepWeek.__table__,
    AnalyticsFactTeamDay.__table__,
    AnalyticsFactScenarioDay.__table__,
    AnalyticsFactCoachingIntervention.__table__,
    AnalyticsFactManagerCalibration.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
