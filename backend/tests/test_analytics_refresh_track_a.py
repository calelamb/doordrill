import time

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.analytics import (
    AnalyticsDimManager,
    AnalyticsDimRep,
    AnalyticsDimScenario,
    AnalyticsDimTeam,
    AnalyticsDimTime,
    AnalyticsFactAlert,
    AnalyticsFactCoachingIntervention,
    AnalyticsFactManagerCalibration,
    AnalyticsFactRepDay,
    AnalyticsFactRepWeek,
    AnalyticsFactScenarioDay,
    AnalyticsFactSession,
    AnalyticsFactSessionTurnMetrics,
    AnalyticsFactTeamDay,
    AnalyticsMaterializedView,
    AnalyticsMetricDefinition,
    AnalyticsMetricSnapshot,
    AnalyticsPartitionWindow,
    AnalyticsRefreshRun,
)
from app.models.scorecard import Scorecard
from app.services.analytics_refresh_service import AnalyticsRefreshService


def _create_assignment(client, seed_org: dict[str, str]) -> dict:
    response = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "retry_policy": {"max_attempts": 2},
        },
    )
    assert response.status_code == 200
    return response.json()


def _run_session(client, seed_org: dict[str, str], assignment_id: str, transcript_hint: str) -> str:
    session = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert session.status_code == 200
    session_id = session.json()["id"]

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {"transcript_hint": transcript_hint, "codec": "opus"},
            }
        )
        for _ in range(80):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


def test_track_a_analytics_warehouse_refresh(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "Hi, I can lower your service price today and schedule a better coverage plan right now.",
    )

    scorecard = None
    for _ in range(30):
        db = SessionLocal()
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        fact_session = db.get(AnalyticsFactSession, session_id)
        db.close()
        if scorecard is not None and fact_session is not None:
            break
        time.sleep(0.03)

    assert scorecard is not None
    assert fact_session is not None

    override = client.patch(
        f"/manager/scorecards/{scorecard.id}",
        json={
            "reviewer_id": seed_org["manager_id"],
            "reason_code": "manager_coaching",
            "override_score": 8.4,
            "notes": "Better close than the model initially credited.",
        },
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert override.status_code == 200

    coaching = client.post(
        f"/manager/scorecards/{scorecard.id}/coaching-notes",
        json={
            "note": "Slow down after the first objection and ask for the next step more directly.",
            "visible_to_rep": True,
            "weakness_tags": ["pace", "closing"],
        },
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert coaching.status_code == 200

    db = SessionLocal()
    try:
        analytics_refresh = AnalyticsRefreshService().backfill_all(db)
        db.commit()
        assert analytics_refresh["refreshed_managers"] >= 1

        assert db.scalar(select(func.count(AnalyticsMetricDefinition.metric_key))) >= 6
        assert db.get(AnalyticsFactSession, session_id) is not None
        assert db.get(AnalyticsFactSessionTurnMetrics, session_id) is not None
        assert db.get(AnalyticsDimManager, seed_org["manager_id"]) is not None
        assert db.get(AnalyticsDimRep, seed_org["rep_id"]) is not None
        assert db.get(AnalyticsDimScenario, seed_org["scenario_id"]) is not None
        team_day = db.scalar(select(AnalyticsFactTeamDay).where(AnalyticsFactTeamDay.manager_id == seed_org["manager_id"]))
        assert team_day is not None
        assert db.get(AnalyticsDimTeam, team_day.team_id) is not None
        assert db.get(AnalyticsDimTime, fact_session.session_date) is not None
        assert db.scalar(select(AnalyticsFactRepDay).where(AnalyticsFactRepDay.rep_id == seed_org["rep_id"])) is not None
        assert db.scalar(select(AnalyticsFactRepWeek).where(AnalyticsFactRepWeek.rep_id == seed_org["rep_id"])) is not None
        assert db.scalar(select(AnalyticsFactScenarioDay).where(AnalyticsFactScenarioDay.scenario_id == seed_org["scenario_id"])) is not None
        assert db.scalar(select(AnalyticsFactManagerCalibration).where(AnalyticsFactManagerCalibration.session_id == session_id)) is not None
        assert db.scalar(select(AnalyticsFactCoachingIntervention).where(AnalyticsFactCoachingIntervention.session_id == session_id)) is not None
        assert db.scalar(select(func.count(AnalyticsFactAlert.id)).where(AnalyticsFactAlert.manager_id == seed_org["manager_id"])) is not None
        assert db.scalar(select(AnalyticsMetricSnapshot).where(AnalyticsMetricSnapshot.manager_id == seed_org["manager_id"])) is not None
        assert db.scalar(
            select(AnalyticsMaterializedView).where(
                AnalyticsMaterializedView.manager_id == seed_org["manager_id"],
                AnalyticsMaterializedView.view_name == "command_center",
                AnalyticsMaterializedView.period_key == "30",
            )
        ) is not None
        assert db.scalar(
            select(func.count(AnalyticsPartitionWindow.id)).where(
                AnalyticsPartitionWindow.table_name == "session_events"
            )
        ) >= 1
        assert db.scalar(select(AnalyticsRefreshRun).where(AnalyticsRefreshRun.scope_type == "session", AnalyticsRefreshRun.scope_id == session_id)) is not None
        assert db.scalar(select(AnalyticsRefreshRun).where(AnalyticsRefreshRun.scope_type == "global")) is not None
    finally:
        db.close()
