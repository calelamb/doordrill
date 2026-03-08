from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api import manager as manager_api
from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.types import AssignmentStatus, EventDirection, SessionStatus, TurnSpeaker


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def _seed_scored_session(
    seed_org: dict[str, str],
    *,
    day_offset: int,
    overall_score: float,
    opening: float,
    objections: float,
    closing: float,
) -> None:
    db = SessionLocal()
    started_at = datetime.now(timezone.utc) - timedelta(days=day_offset)

    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "rep_insight_test"},
    )
    db.add(assignment)
    db.flush()

    session = DrillSession(
        assignment_id=assignment.id,
        rep_id=seed_org["rep_id"],
        scenario_id=seed_org["scenario_id"],
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=4),
        duration_seconds=240,
        status=SessionStatus.GRADED,
    )
    db.add(session)
    db.flush()

    rep_turn = SessionTurn(
        session_id=session.id,
        turn_index=1,
        speaker=TurnSpeaker.REP,
        stage="opening",
        text="Quick question before I go, are bugs getting worse this month?",
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=10),
        objection_tags=[],
    )
    ai_turn = SessionTurn(
        session_id=session.id,
        turn_index=2,
        speaker=TurnSpeaker.AI,
        stage="objection_handling",
        text="We already have service and I do not want to switch.",
        started_at=started_at + timedelta(seconds=12),
        ended_at=started_at + timedelta(seconds=24),
        objection_tags=["incumbent_provider"],
    )
    db.add_all([rep_turn, ai_turn])
    db.flush()

    db.add_all(
        [
            SessionEvent(
                session_id=session.id,
                event_id=f"{session.id}-emotion-1",
                event_type="server.session.state",
                direction=EventDirection.SERVER,
                sequence=1,
                event_ts=started_at + timedelta(seconds=5),
                payload={"emotion": "skeptical"},
            ),
            SessionEvent(
                session_id=session.id,
                event_id=f"{session.id}-emotion-2",
                event_type="server.session.state",
                direction=EventDirection.SERVER,
                sequence=2,
                event_ts=started_at + timedelta(seconds=20),
                payload={"emotion": "neutral"},
            ),
        ]
    )

    scorecard = Scorecard(
        session_id=session.id,
        overall_score=overall_score,
        category_scores={
            "opening": {"score": opening, "evidence_turn_ids": [rep_turn.id]},
            "pitch_delivery": {"score": 6.0, "evidence_turn_ids": [rep_turn.id]},
            "objection_handling": {"score": objections, "evidence_turn_ids": [ai_turn.id]},
            "closing_technique": {"score": closing, "evidence_turn_ids": [rep_turn.id]},
            "professionalism": {"score": 7.3, "evidence_turn_ids": [rep_turn.id]},
        },
        highlights=[{"type": "improve", "note": "Did not hold frame on the switch objection", "turn_id": ai_turn.id}],
        ai_summary="Strong opening, but the rep lost conviction once the homeowner mentioned an existing provider.",
        evidence_turn_ids=[rep_turn.id, ai_turn.id],
        weakness_tags=["objection_handling", "closing"],
    )
    db.add(scorecard)
    db.commit()
    db.close()


def test_rep_insight_includes_adaptive_profile(client, seed_org, monkeypatch):
    manager_api.manager_ai_service.rep_insight_cache.clear()
    _seed_scored_session(seed_org, day_offset=6, overall_score=5.8, opening=6.2, objections=5.1, closing=5.4)
    _seed_scored_session(seed_org, day_offset=3, overall_score=6.4, opening=6.8, objections=5.8, closing=5.9)
    _seed_scored_session(seed_org, day_offset=1, overall_score=6.9, opening=7.0, objections=6.2, closing=6.4)

    def fake_claude(*, system_prompt: str, user_prompt: str, max_tokens: int):
        assert "Adaptive skill profile:" in user_prompt
        assert "Recommended difficulty:" in user_prompt
        assert "Emotion recovery average across recent sessions:" in user_prompt
        assert "Override signal:" in user_prompt
        assert "Readiness trajectory:" in user_prompt
        return {
            "headline": "Ray is improving but still fades at the close",
            "primary_weakness": "Closing consistency",
            "root_cause": "He enters the close with better control than before, but his conviction drops after the first pushback. That leaves the ask too soft and too late.",
            "drill_recommendation": 'Assign "Skeptical Homeowner" at the next recommended difficulty',
            "coaching_script": "Ray, your opener is trending up, which gives you more chances to close. The miss is that you stop pressing for a next step once resistance shows up. Keep the same composure, then ask for the commitment directly before the homeowner resets the frame.",
            "expected_improvement": "+0.7 on closing within 2 sessions",
        }

    monkeypatch.setattr(manager_api.manager_ai_service, "_call_claude_json", fake_claude)

    response = client.post(
        "/manager/ai/rep-insight",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "rep_id": seed_org["rep_id"], "period_days": 30},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["adaptive_skill_profile"]
    assert body["adaptive_skill_profile"][0]["skill"] == "opening"
    assert "sessions_to_readiness" in body["readiness_trajectory"]
    assert body["readiness_trajectory"]["trajectory_per_skill"]
    assert body["override_signal"]["override_count"] == 0
    assert body["data_summary"]["adaptive_plan"]["recommended_difficulty"] >= 1
    assert body["data_summary"]["emotion_recovery_average"] > 0
