from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api import manager as manager_api
from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.transcript import ObjectionType  # noqa: F401
from app.models.types import AssignmentStatus, SessionStatus, TurnSpeaker, UserRole
from app.models.user import User
from app.models.warehouse import FactRepDaily


@pytest.fixture(autouse=True)
def clear_weekly_team_briefing_cache() -> None:
    manager_api.manager_ai_service.weekly_team_briefing_cache.clear()


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def _create_second_rep(seed_org: dict[str, str]) -> str:
    db = SessionLocal()
    manager = db.get(User, seed_org["manager_id"])
    assert manager is not None
    rep = User(
        org_id=seed_org["org_id"],
        role=UserRole.REP,
        name="Nina Newleaf",
        email="nina@example.com",
        team_id=manager.team_id,
    )
    db.add(rep)
    db.commit()
    db.refresh(rep)
    rep_id = rep.id
    db.close()
    return rep_id


def _seed_weekly_session(
    seed_org: dict[str, str],
    *,
    rep_id: str,
    rep_name: str,
    day_offset: int,
    overall_score: float,
    objection_score: float,
    closing_score: float,
    weakness_tags: list[str],
) -> None:
    db = SessionLocal()
    started_at = datetime.now(timezone.utc) - timedelta(days=day_offset)

    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=rep_id,
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "weekly_team_briefing_test"},
    )
    db.add(assignment)
    db.flush()

    session = DrillSession(
        assignment_id=assignment.id,
        rep_id=rep_id,
        scenario_id=seed_org["scenario_id"],
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=5),
        duration_seconds=300,
        status=SessionStatus.GRADED,
    )
    db.add(session)
    db.flush()

    rep_turn = SessionTurn(
        session_id=session.id,
        turn_index=1,
        speaker=TurnSpeaker.REP,
        stage="opening",
        text=f"{rep_name} opens with a quick pitch and tries to set up the close.",
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=10),
        objection_tags=[],
    )
    ai_turn = SessionTurn(
        session_id=session.id,
        turn_index=2,
        speaker=TurnSpeaker.AI,
        stage="objection_handling",
        text="I need to think about it before making a change.",
        started_at=started_at + timedelta(seconds=12),
        ended_at=started_at + timedelta(seconds=24),
        objection_tags=["timing"],
    )
    db.add_all([rep_turn, ai_turn])
    db.flush()

    db.add(
        Scorecard(
            session_id=session.id,
            overall_score=overall_score,
            category_scores={
                "opening": {"score": 7.0},
                "pitch_delivery": {"score": 6.5},
                "objection_handling": {"score": objection_score},
                "closing_technique": {"score": closing_score},
                "professionalism": {"score": 7.4},
            },
            highlights=[{"type": "improve", "note": "Need stronger control at the decision point", "turn_id": rep_turn.id}],
            ai_summary=f"{rep_name} had a solid start but the decision point still created friction.",
            evidence_turn_ids=[rep_turn.id],
            weakness_tags=weakness_tags,
        )
    )
    db.add(
        FactRepDaily(
            rep_id=rep_id,
            org_id=seed_org["org_id"],
            manager_id=seed_org["manager_id"],
            session_date=started_at.date(),
            session_count=1,
            scored_count=1,
            avg_score=overall_score,
            min_score=overall_score,
            max_score=overall_score,
            avg_objection_handling=objection_score,
            avg_closing_technique=closing_score,
            total_duration_seconds=300,
            barge_in_count=0,
            override_count=0,
            coaching_note_count=0,
        )
    )
    db.commit()
    db.close()


def test_weekly_team_briefing_structure(client, seed_org, monkeypatch):
    second_rep_id = _create_second_rep(seed_org)
    _seed_weekly_session(
        seed_org,
        rep_id=seed_org["rep_id"],
        rep_name="Ray Rep",
        day_offset=1,
        overall_score=7.2,
        objection_score=6.4,
        closing_score=6.8,
        weakness_tags=["closing"],
    )
    _seed_weekly_session(
        seed_org,
        rep_id=seed_org["rep_id"],
        rep_name="Ray Rep",
        day_offset=3,
        overall_score=6.8,
        objection_score=6.1,
        closing_score=6.2,
        weakness_tags=["closing"],
    )
    _seed_weekly_session(
        seed_org,
        rep_id=second_rep_id,
        rep_name="Nina Newleaf",
        day_offset=2,
        overall_score=5.9,
        objection_score=5.0,
        closing_score=4.9,
        weakness_tags=["objection_handling", "closing"],
    )

    call_count = {"value": 0}

    def fake_claude(*, system_prompt: str, user_prompt: str, max_tokens: int):
        call_count["value"] += 1
        assert "Rep summaries:" in user_prompt
        assert "Team average score:" in user_prompt
        assert "Most common weakness tag:" in user_prompt
        return {
            "team_pulse": "The team is generating enough volume to coach from, but closing consistency is still separating the best reps from the rest. Ray is pushing upward while Nina needs a tighter objection-to-close handoff.",
            "standout_rep": {
                "name": "Ray Rep",
                "why": "Ray averaged 7.0 across two scored sessions this week and is carrying the strongest closing score on the team.",
            },
            "needs_attention": [
                {
                    "name": "Nina Newleaf",
                    "concern": "Nina posted a 5.9 weekly score with closing under 5.0, so she still loses control at the decision point.",
                }
            ],
            "shared_weakness": {
                "skill": "closing",
                "team_average": 5.97,
                "note": "The common miss is getting to the ask and then softening as soon as the homeowner hesitates.",
            },
            "huddle_topic": {
                "topic": "Hold the frame through the close",
                "suggested_talking_points": [
                    "Show one example of a strong next-step ask that comes immediately after the objection is handled.",
                    "Call out how quickly the homeowner regains control when the rep adds extra explanation instead of asking.",
                    "End the huddle by assigning one repetition block on the close for every rep below a 6.0 closing average.",
                ],
            },
            "manager_action_items": [
                "Assign Nina one difficulty-2 close-attempt scenario before Friday and review the replay the same day.",
                "Use Ray's latest session as the huddle example for how to carry objection recovery into the ask.",
            ],
        }

    monkeypatch.setattr(manager_api.manager_ai_service, "_call_claude_json", fake_claude)

    response = client.post(
        "/manager/team/weekly-briefing",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manager_id"] == seed_org["manager_id"]
    assert body["team_pulse"]
    assert body["standout_rep"]["name"] == "Ray Rep"
    assert len(body["needs_attention"]) <= 2
    assert body["shared_weakness"]["skill"] == "closing"
    assert len(body["huddle_topic"]["suggested_talking_points"]) == 3
    assert len(body["manager_action_items"]) >= 1
    assert body["data_summary"]["rep_count_considered"] == 2
    assert body["data_summary"]["rep_summaries"]

    cached = client.post(
        "/manager/team/weekly-briefing",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"]},
    )
    assert cached.status_code == 200
    assert cached.json() == body
    assert call_count["value"] == 1


def test_weekly_team_briefing_uses_predictive_at_risk_reps(client, seed_org, monkeypatch):
    second_rep_id = _create_second_rep(seed_org)
    for offset in range(5):
        _seed_weekly_session(
            seed_org,
            rep_id=second_rep_id,
            rep_name="Nina Newleaf",
            day_offset=offset + 1,
            overall_score=5.0,
            objection_score=5.0,
            closing_score=5.0,
            weakness_tags=["closing"],
        )

    monkeypatch.setattr(
        manager_api.manager_ai_service,
        "_call_claude_json",
        lambda **kwargs: {
            "team_pulse": "The team has enough reps this week to spot stable patterns.",
            "standout_rep": {"name": "Nina Newleaf", "why": "She logged the most recent practice volume this week."},
            "needs_attention": [],
            "shared_weakness": {
                "skill": "closing",
                "team_average": 5.0,
                "note": "The close is still too soft across the week.",
            },
            "huddle_topic": {
                "topic": "Finish the ask cleanly",
                "suggested_talking_points": [
                    "Show the exact ask.",
                    "Strip extra explanation after the objection.",
                    "End with a direct commitment request.",
                ],
            },
            "manager_action_items": ["Review Nina's latest five reps for plateau patterns."],
        },
    )

    response = client.post(
        "/manager/team/weekly-briefing",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["needs_attention"]
    assert body["needs_attention"][0]["name"] == "Nina Newleaf"
    assert body["data_summary"]["at_risk_reps"][0]["rep_id"] == second_rep_id
