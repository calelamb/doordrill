from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus


LOCAL_TZ = ZoneInfo("America/Denver")


def _rep_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["rep_id"], "x-user-role": "rep"}


def _local_noon(days_ago: int) -> datetime:
    local_now = datetime.now(LOCAL_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    return (local_now - timedelta(days=days_ago)).astimezone(timezone.utc)


def _category_scores(
    *,
    opening: float,
    pitch_delivery: float,
    objection_handling: float,
    closing_technique: float,
    professionalism: float,
) -> dict[str, float]:
    return {
        "opening": opening,
        "pitch_delivery": pitch_delivery,
        "objection_handling": objection_handling,
        "closing_technique": closing_technique,
        "professionalism": professionalism,
    }


def _seed_scored_session(
    seed_org: dict[str, str],
    *,
    started_at: datetime,
    overall_score: float,
    category_scores: dict[str, float],
) -> str:
    db = SessionLocal()

    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "rep_progress_streak_test"},
    )
    db.add(assignment)
    db.flush()

    session = DrillSession(
        assignment_id=assignment.id,
        rep_id=seed_org["rep_id"],
        scenario_id=seed_org["scenario_id"],
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
            scorecard_schema_version="v1",
            category_scores=category_scores,
            highlights=[],
            ai_summary="Rep progress streak test scorecard.",
            evidence_turn_ids=[],
            weakness_tags=[],
        )
    )
    db.commit()
    session_id = session.id
    db.close()
    return session_id


def test_streak_counts_consecutive_days(client, seed_org):
    for days_ago, score in enumerate([8.2, 7.6, 7.1]):
        _seed_scored_session(
            seed_org,
            started_at=_local_noon(days_ago),
            overall_score=score,
            category_scores=_category_scores(
                opening=7.0,
                pitch_delivery=7.0,
                objection_handling=score,
                closing_technique=6.8,
                professionalism=8.0,
            ),
        )

    response = client.get("/rep/progress", params={"rep_id": seed_org["rep_id"]}, headers=_rep_headers(seed_org))

    assert response.status_code == 200
    assert response.json()["streak_days"] == 3


def test_streak_resets_on_gap_day(client, seed_org):
    for days_ago, score in [(2, 6.8), (3, 7.1)]:
        _seed_scored_session(
            seed_org,
            started_at=_local_noon(days_ago),
            overall_score=score,
            category_scores=_category_scores(
                opening=6.5,
                pitch_delivery=6.2,
                objection_handling=6.0,
                closing_technique=6.4,
                professionalism=7.4,
            ),
        )

    response = client.get("/rep/progress", params={"rep_id": seed_org["rep_id"]}, headers=_rep_headers(seed_org))

    assert response.status_code == 200
    assert response.json()["streak_days"] == 0


def test_personal_best_returns_highest_score(client, seed_org):
    session_ids = [
        _seed_scored_session(
            seed_org,
            started_at=_local_noon(5),
            overall_score=6.4,
            category_scores=_category_scores(
                opening=6.0,
                pitch_delivery=6.2,
                objection_handling=6.1,
                closing_technique=6.5,
                professionalism=7.0,
            ),
        ),
        _seed_scored_session(
            seed_org,
            started_at=_local_noon(4),
            overall_score=8.9,
            category_scores=_category_scores(
                opening=8.6,
                pitch_delivery=8.5,
                objection_handling=9.0,
                closing_technique=8.8,
                professionalism=9.2,
            ),
        ),
        _seed_scored_session(
            seed_org,
            started_at=_local_noon(3),
            overall_score=7.7,
            category_scores=_category_scores(
                opening=7.5,
                pitch_delivery=7.4,
                objection_handling=7.9,
                closing_technique=7.6,
                professionalism=8.0,
            ),
        ),
    ]

    response = client.get("/rep/progress", params={"rep_id": seed_org["rep_id"]}, headers=_rep_headers(seed_org))

    assert response.status_code == 200
    body = response.json()
    assert body["personal_best"] == 8.9
    assert body["personal_best_session_id"] == session_ids[1]


def test_most_improved_category_correct(client, seed_org):
    opening_scores = [5.0, 5.1, 5.2, 5.8, 6.0, 6.1]
    pitch_scores = [5.4, 5.4, 5.5, 6.0, 6.0, 6.1]
    objection_scores = [3.0, 4.0, 4.0, 7.0, 8.0, 8.0]
    closing_scores = [5.2, 5.2, 5.3, 5.9, 6.0, 6.1]
    professionalism_scores = [7.0, 7.1, 7.0, 7.6, 7.5, 7.6]
    overall_scores = [5.1, 5.3, 5.4, 7.1, 7.6, 7.8]

    for index in range(6):
        _seed_scored_session(
            seed_org,
            started_at=_local_noon(10 - index),
            overall_score=overall_scores[index],
            category_scores=_category_scores(
                opening=opening_scores[index],
                pitch_delivery=pitch_scores[index],
                objection_handling=objection_scores[index],
                closing_technique=closing_scores[index],
                professionalism=professionalism_scores[index],
            ),
        )

    response = client.get("/rep/progress", params={"rep_id": seed_org["rep_id"]}, headers=_rep_headers(seed_org))

    assert response.status_code == 200
    body = response.json()
    assert body["most_improved_category"] == "objection_handling"
    assert body["most_improved_delta"] == 4.0
