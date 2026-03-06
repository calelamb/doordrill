from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus, UserRole
from app.models.user import User


def _category_scores(
    *,
    opening: float,
    pitch: float,
    objection: float,
    closing: float,
    professionalism: float,
) -> dict[str, dict[str, float]]:
    return {
        "opening": {"score": opening},
        "pitch": {"score": pitch},
        "objection_handling": {"score": objection},
        "closing": {"score": closing},
        "professionalism": {"score": professionalism},
    }


def _insert_scored_session(
    db,
    *,
    rep_id: str,
    manager_id: str,
    scenario_id: str,
    started_at: datetime,
    overall_score: float,
    category_scores: dict[str, dict[str, float]],
) -> None:
    assignment = Assignment(
        scenario_id=scenario_id,
        rep_id=rep_id,
        assigned_by=manager_id,
        status=AssignmentStatus.COMPLETED,
        retry_policy={"max_attempts": 2},
    )
    db.add(assignment)
    db.flush()

    session = DrillSession(
        assignment_id=assignment.id,
        rep_id=rep_id,
        scenario_id=scenario_id,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=6),
        duration_seconds=360,
        status=SessionStatus.GRADED,
    )
    db.add(session)
    db.flush()

    db.add(
        Scorecard(
            session_id=session.id,
            overall_score=overall_score,
            category_scores=category_scores,
            highlights=[],
            ai_summary="Seeded scorecard",
            evidence_turn_ids=[],
            weakness_tags=[],
        )
    )
    db.flush()


def test_rep_risk_detail_endpoint_returns_deterministic_signals(client, seed_org):
    now = datetime.now(timezone.utc).replace(microsecond=0)

    db = SessionLocal()
    existing_rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
    manager = db.scalar(select(User).where(User.id == seed_org["manager_id"]))
    scenario = db.scalar(select(Scenario).where(Scenario.id == seed_org["scenario_id"]))

    assert existing_rep is not None
    assert manager is not None
    assert scenario is not None

    existing_rep.name = "Parker Plateau"

    jordan = User(
        org_id=manager.org_id,
        team_id=manager.team_id,
        role=UserRole.REP,
        name="Jordan Decline",
        email="jordan.decline@example.com",
    )
    marcus = User(
        org_id=manager.org_id,
        team_id=manager.team_id,
        role=UserRole.REP,
        name="Marcus Stall",
        email="marcus.stall@example.com",
    )
    sarah = User(
        org_id=manager.org_id,
        team_id=manager.team_id,
        role=UserRole.REP,
        name="Sarah Rising",
        email="sarah.rising@example.com",
    )
    db.add_all([jordan, marcus, sarah])
    db.flush()

    plateau_scores = [6.0, 6.1, 5.9, 6.1, 6.0, 6.2, 6.1, 6.0]
    for offset, score in enumerate(plateau_scores):
        _insert_scored_session(
            db,
            rep_id=existing_rep.id,
            manager_id=manager.id,
            scenario_id=scenario.id,
            started_at=now - timedelta(days=8 - offset),
            overall_score=score,
            category_scores=_category_scores(
                opening=6.5,
                pitch=6.2,
                objection=4.1,
                closing=6.0,
                professionalism=6.7,
            ),
        )

    decline_scores = [7.6, 7.3, 7.1, 6.8, 6.5, 6.2, 5.9, 5.6, 5.3, 5.0]
    for offset, score in enumerate(decline_scores):
        _insert_scored_session(
            db,
            rep_id=jordan.id,
            manager_id=manager.id,
            scenario_id=scenario.id,
            started_at=now - timedelta(days=10 - offset),
            overall_score=score,
            category_scores=_category_scores(
                opening=6.8,
                pitch=6.4,
                objection=5.2,
                closing=4.0,
                professionalism=6.3,
            ),
        )

    _insert_scored_session(
        db,
        rep_id=marcus.id,
        manager_id=manager.id,
        scenario_id=scenario.id,
        started_at=now - timedelta(days=18),
        overall_score=5.8,
        category_scores=_category_scores(
            opening=5.9,
            pitch=5.8,
            objection=4.8,
            closing=5.2,
            professionalism=6.0,
        ),
    )

    rising_scores = [7.4, 7.7, 8.0, 8.3, 8.6, 8.9, 9.1, 9.3, 9.5, 9.7]
    for offset, score in enumerate(rising_scores):
        _insert_scored_session(
            db,
            rep_id=sarah.id,
            manager_id=manager.id,
            scenario_id=scenario.id,
            started_at=now - timedelta(days=10 - offset),
            overall_score=score,
            category_scores=_category_scores(
                opening=8.7,
                pitch=8.8,
                objection=8.6,
                closing=8.5,
                professionalism=8.9,
            ),
        )

    db.commit()
    db.close()

    manager_headers = {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}
    response = client.get(
        "/manager/analytics/rep-risk-detail",
        params={"manager_id": seed_org["manager_id"], "period": 30},
        headers=manager_headers,
    )

    assert response.status_code == 200
    body = response.json()

    assert body["manager_id"] == seed_org["manager_id"]
    assert body["period"] == "30"
    assert body["team_avg_score"] is not None
    assert set(body["team_category_averages"]).issuperset(
        {"opening", "pitch", "objection_handling", "closing", "professionalism"}
    )

    reps = body["reps"]
    assert reps == sorted(reps, key=lambda item: (item["risk_score"], item["red_flag_count"], item["session_count"]), reverse=True)

    by_name = {item["rep_name"]: item for item in reps}

    plateau = by_name["Parker Plateau"]
    assert plateau["plateau_detected"] is True
    assert plateau["decline_detected"] is False
    assert plateau["score_volatility"] < 0.4
    assert plateau["most_vulnerable_category"] == "objection_handling"
    assert plateau["category_gap_vs_team"] > 0
    assert plateau["session_count"] == 8

    declining = by_name["Jordan Decline"]
    assert declining["decline_detected"] is True
    assert declining["plateau_detected"] is False
    assert declining["breakthrough_detected"] is False
    assert declining["score_trend_slope"] < -0.15
    assert declining["projected_score_10_sessions"] < declining["current_avg_score"]
    assert declining["most_vulnerable_category"] == "closing"
    assert declining["risk_level"] == "high"

    stalled = by_name["Marcus Stall"]
    assert stalled["stall_detected"] is True
    assert stalled["days_since_last_session"] >= 18
    assert stalled["risk_level"] == "high"

    rising = by_name["Sarah Rising"]
    assert rising["breakthrough_detected"] is True
    assert rising["decline_detected"] is False
    assert rising["projected_score_10_sessions"] > rising["current_avg_score"]
    assert rising["risk_level"] == "low"
