from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api import manager as manager_api
from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionEvent, SessionTurn
from app.models.training import AdaptiveRecommendationOutcome, OverrideLabel
from app.models.types import AssignmentStatus, EventDirection, ReviewReason, SessionStatus, TurnSpeaker
from tests.test_adaptive_training import _seed_adaptive_history


@pytest.fixture(autouse=True)
def clear_one_on_one_cache() -> None:
    manager_api.manager_ai_service.one_on_one_prep_cache.clear()


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def _ensure_prompt_version(db) -> PromptVersion:
    prompt_version = db.query(PromptVersion).filter_by(prompt_type="grading_v2", version="1.0.0").one_or_none()
    if prompt_version is not None:
        return prompt_version

    prompt_version = PromptVersion(
        prompt_type="grading_v2",
        version="1.0.0",
        content="test prompt",
        active=True,
    )
    db.add(prompt_version)
    db.flush()
    return prompt_version


def _seed_recent_prep_data(seed_org: dict[str, str]) -> None:
    db = SessionLocal()
    started_at = datetime.now(timezone.utc) - timedelta(hours=18)

    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"source": "one_on_one_prep_test"},
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

    db.add_all(
        [
            SessionEvent(
                session_id=session.id,
                event_id=f"{session.id}-emotion-start",
                event_type="server.session.state",
                direction=EventDirection.SERVER,
                sequence=1,
                event_ts=started_at + timedelta(seconds=5),
                payload={"emotion": "annoyed"},
            ),
            SessionEvent(
                session_id=session.id,
                event_id=f"{session.id}-emotion-end",
                event_type="server.turn.committed",
                direction=EventDirection.SERVER,
                sequence=2,
                event_ts=started_at + timedelta(minutes=5),
                payload={"emotion": "skeptical"},
            ),
            SessionTurn(
                session_id=session.id,
                turn_index=1,
                speaker=TurnSpeaker.REP,
                stage="opening",
                text="I can show you why most homeowners switch before renewal hits.",
                started_at=started_at + timedelta(seconds=30),
                ended_at=started_at + timedelta(seconds=40),
                objection_tags=[],
            ),
            SessionTurn(
                session_id=session.id,
                turn_index=2,
                speaker=TurnSpeaker.AI,
                stage="close_attempt",
                text="I don't want to make a change today.",
                started_at=started_at + timedelta(minutes=2),
                ended_at=started_at + timedelta(minutes=2, seconds=10),
                objection_tags=["timing"],
            ),
        ]
    )
    db.flush()

    scorecard = Scorecard(
        session_id=session.id,
        overall_score=6.3,
        category_scores={
            "opening": {"score": 7.4},
            "pitch_delivery": {"score": 6.6},
            "objection_handling": {"score": 5.8},
            "closing_technique": {"score": 5.1},
            "professionalism": {"score": 7.6},
        },
        highlights=[{"type": "improve", "note": "Close softened after the first brush-off"}],
        ai_summary="The rep entered the close in a solid position, then backed off once the homeowner stalled.",
        evidence_turn_ids=[],
        weakness_tags=["closing", "timing"],
    )
    db.add(scorecard)
    db.flush()

    db.add(
        ManagerCoachingNote(
            scorecard_id=scorecard.id,
            reviewer_id=seed_org["manager_id"],
            note="Press for the next step before the homeowner resets the frame.",
            visible_to_rep=True,
            weakness_tags=["closing"],
        )
    )

    prompt_version = _ensure_prompt_version(db)
    grading_run = GradingRun(
        session_id=session.id,
        scorecard_id=scorecard.id,
        prompt_version_id=prompt_version.id,
        model_name="gpt-test",
        model_latency_ms=100,
        input_token_count=250,
        output_token_count=140,
        status="success",
        raw_llm_response="{}",
        parse_error=None,
        overall_score=6.3,
        confidence_score=0.78,
        started_at=started_at + timedelta(minutes=5, seconds=30),
        completed_at=started_at + timedelta(minutes=5, seconds=35),
    )
    db.add(grading_run)
    db.flush()

    review = ManagerReview(
        scorecard_id=scorecard.id,
        reviewer_id=seed_org["manager_id"],
        reviewed_at=started_at + timedelta(minutes=6),
        reason_code=ReviewReason.MANAGER_COACHING,
        override_score=7.2,
        notes="Manager thought the close earned more credit than the model gave it.",
    )
    db.add(review)
    db.flush()

    db.add(
        OverrideLabel(
            review_id=review.id,
            grading_run_id=grading_run.id,
            session_id=session.id,
            manager_id=seed_org["manager_id"],
            org_id=seed_org["org_id"],
            ai_overall_score=6.3,
            ai_category_scores=scorecard.category_scores,
            override_overall_score=7.2,
            override_category_scores={
                "closing_technique": {"score": 7.4},
                "objection_handling": {"score": 6.3},
            },
            override_reason_text=review.notes,
            override_delta_overall=0.9,
            is_high_disagreement=False,
            label_quality="medium",
        )
    )

    db.add(
        AdaptiveRecommendationOutcome(
            assignment_id=assignment.id,
            session_id=session.id,
            rep_id=seed_org["rep_id"],
            manager_id=seed_org["manager_id"],
            recommended_scenario_id=seed_org["scenario_id"],
            recommended_difficulty=3,
            recommended_focus_skills=["closing", "objection_handling"],
            baseline_skill_scores={"closing": 4.8, "objection_handling": 5.2},
            baseline_overall_score=5.9,
            outcome_skill_scores={"closing": 5.8, "objection_handling": 5.9},
            outcome_overall_score=6.3,
            skill_delta={"closing": 1.0, "objection_handling": 0.7},
            recommendation_success=True,
            outcome_written_at=started_at + timedelta(minutes=7),
        )
    )
    db.commit()
    db.close()


def test_one_on_one_prep_structure(client, seed_org, monkeypatch):
    _seed_adaptive_history(seed_org)
    _seed_recent_prep_data(seed_org)

    call_count = {"value": 0}

    def fake_claude(*, system_prompt: str, user_prompt: str, max_tokens: int):
        call_count["value"] += 1
        assert "Last 5 sessions:" in user_prompt
        assert "Recent adaptive recommendation outcomes:" in user_prompt
        assert "Coaching note themes:" in user_prompt
        assert "Override signal:" in user_prompt
        return {
            "discussion_topics": [
                {
                    "topic": "Closing stalls after the first brush-off",
                    "evidence": "Closing moved from 4.1 and 4.4 in prior adaptive sessions to 5.1 in the latest session, but it is still the weakest current category.",
                    "suggested_opener": "You are earning the right to close, but the ask still softens as soon as the homeowner hesitates.",
                },
                {
                    "topic": "Objection recovery is improving enough to press harder",
                    "evidence": "Objection handling improved from 4.8 to 5.8 across the recent sample, and the latest recommendation outcome showed a +0.7 objection delta.",
                    "suggested_opener": "You handled the pushback better this week, so now we need to cash that out into a firmer next-step ask.",
                },
                {
                    "topic": "Manager feedback is consistently pointing at close control",
                    "evidence": "The latest coaching note tagged closing, and the only override in the period added +0.9 overall with closing as the biggest corrected category.",
                    "suggested_opener": "My note to you was not about effort; it was about holding the frame long enough to ask confidently.",
                },
            ],
            "strength_to_acknowledge": {
                "skill": "Opening",
                "what_to_say": "Your opener is buying you time because it is clear and direct. That progress matters because it creates more real chances to work through resistance.",
            },
            "pattern_to_challenge": {
                "skill": "Closing",
                "pattern": "Once the homeowner slows the conversation, you shift from guiding the next step to protecting the interaction.",
                "what_to_say": "When you feel that slowdown, that is your cue to get more direct, not less. Ask for the commitment before the homeowner resets the pace.",
            },
            "suggested_next_scenario": {
                "scenario_type": "Skeptical Homeowner",
                "difficulty": 3,
                "rationale": "The adaptive plan is already recommending level 3 work, and that is the right place to practice holding the close after resistance.",
            },
            "readiness_summary": "Ray is trending up and can handle more resistance, but he is not yet consistently turning improved objection work into committed next steps.",
        }

    monkeypatch.setattr(manager_api.manager_ai_service, "_call_claude_json", fake_claude)

    response = client.post(
        f"/manager/reps/{seed_org['rep_id']}/one-on-one-prep",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "period_days": 14},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rep_id"] == seed_org["rep_id"]
    assert body["manager_id"] == seed_org["manager_id"]
    assert len(body["discussion_topics"]) == 3
    assert body["discussion_topics"][0]["evidence"]
    assert body["strength_to_acknowledge"]["skill"] == "Opening"
    assert body["pattern_to_challenge"]["skill"] == "Closing"
    assert body["suggested_next_scenario"]["difficulty"] == 3
    assert body["readiness_summary"]
    assert body["data_summary"]["recent_sessions"]
    assert body["data_summary"]["adaptive_outcomes"]
    assert body["data_summary"]["override_signal"]["override_count"] >= 1

    cached = client.post(
        f"/manager/reps/{seed_org['rep_id']}/one-on-one-prep",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "period_days": 14},
    )
    assert cached.status_code == 200
    assert cached.json() == body
    assert call_count["value"] == 1
