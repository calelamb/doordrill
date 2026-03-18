from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.prompt_version import PromptVersion
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, SessionStatus
from app.models.user import User
from app.services.manager_ai_coaching_service import (
    DEFAULT_COACHING_SYSTEM_PREFIX,
    ManagerAiCoachingService,
)


def _seed_minimal_one_on_one_session(seed_org: dict[str, str]) -> None:
    db = SessionLocal()
    try:
        started_at = datetime.now(timezone.utc) - timedelta(days=1)
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "coaching_prompt_injection_test"},
        )
        db.add(assignment)
        db.flush()

        session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=seed_org["scenario_id"],
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=5),
            duration_seconds=300,
            status=SessionStatus.GRADED,
        )
        db.add(session)
        db.flush()

        db.add(
            Scorecard(
                session_id=session.id,
                overall_score=6.4,
                category_scores={
                    "opening": {"score": 7.1},
                    "pitch_delivery": {"score": 6.6},
                    "objection_handling": {"score": 5.8},
                    "closing_technique": {"score": 5.7},
                    "professionalism": {"score": 6.9},
                },
                highlights=[{"type": "improve", "note": "Needs a stronger objection pivot"}],
                ai_summary="The rep handled the opener well but softened too early on the first objection.",
                evidence_turn_ids=[],
                weakness_tags=["objection_handling", "closing"],
            )
        )
        db.commit()
    finally:
        db.close()


def test_get_coaching_system_prefix_returns_active_prompt_content():
    db = SessionLocal()
    try:
        db.add(
            PromptVersion(
                prompt_type="coaching",
                version="coaching_custom",
                content="Custom coaching system prefix.",
                active=True,
            )
        )
        db.commit()

        service = ManagerAiCoachingService()
        assert service._get_coaching_system_prefix(db) == "Custom coaching system prefix."
    finally:
        db.close()


def test_get_coaching_system_prefix_falls_back_to_default_when_no_active_row():
    db = SessionLocal()
    try:
        service = ManagerAiCoachingService()
        assert service._get_coaching_system_prefix(db) == DEFAULT_COACHING_SYSTEM_PREFIX
    finally:
        db.close()


def test_generate_one_on_one_prep_includes_coaching_prefix_in_system_message(seed_org, monkeypatch):
    _seed_minimal_one_on_one_session(seed_org)

    db = SessionLocal()
    try:
        db.add(
            PromptVersion(
                prompt_type="coaching",
                version="coaching_prefix_test",
                content="Coaching prefix from prompt version.",
                active=True,
            )
        )
        db.commit()

        manager = db.get(User, seed_org["manager_id"])
        rep = db.get(User, seed_org["rep_id"])
        assert manager is not None
        assert rep is not None

        service = ManagerAiCoachingService()
        monkeypatch.setattr(
            service.adaptive_training_service,
            "_build_session_snapshot",
            lambda session, scenario: {"skills": {}, "emotion_recovery": 0.0},
        )
        monkeypatch.setattr(
            service.adaptive_training_service,
            "build_plan",
            lambda db, rep_id: {
                "skill_profile": [],
                "recommended_scenarios": [],
                "readiness_score": 0.0,
                "recommended_difficulty": 2,
                "weakest_skills": ["objection_handling"],
            },
        )
        monkeypatch.setattr(
            service,
            "_get_company_training_context",
            lambda *args, **kwargs: None,
        )

        captured: dict[str, str] = {}

        def fake_claude(*, system_prompt: str, user_prompt: str, max_tokens: int, model: str | None = None):
            captured["system_prompt"] = system_prompt
            captured["user_prompt"] = user_prompt
            return {
                "discussion_topics": [
                    {
                        "topic": "Handle the first objection with more control",
                        "evidence": "The latest scorecard put objection handling at 5.8 while the overall score stayed at 6.4.",
                        "suggested_opener": "You are getting enough at-bats now that the first objection should not reset the whole conversation.",
                    },
                    {
                        "topic": "Carry momentum into the close",
                        "evidence": "Closing landed at 5.7, so the rep still loses the frame after a decent opener.",
                        "suggested_opener": "Once you earn the next thirty seconds, we need you to protect the frame and ask with more confidence.",
                    },
                    {
                        "topic": "Build a repeatable objection bridge",
                        "evidence": "The weakness tags still center on objection handling, which matches the latest AI summary.",
                        "suggested_opener": "Let’s script one bridge you can repeat until the response sounds automatic.",
                    },
                ],
                "strength_to_acknowledge": {
                    "skill": "Opening",
                    "what_to_say": "Your opener is buying enough attention to work with, so the foundation is there.",
                },
                "pattern_to_challenge": {
                    "skill": "Objection Handling",
                    "pattern": "The rep softens after the first objection instead of keeping control of the frame.",
                    "what_to_say": "Acknowledge the concern once, then pivot into a tighter question before you defend the offer.",
                },
                "suggested_next_scenario": {
                    "scenario_type": "Skeptical Homeowner",
                    "difficulty": 2,
                    "rationale": "It keeps the objection load realistic while forcing one cleaner pivot before the close.",
                },
                "readiness_summary": "The rep is progressing, but objection handling still needs one repeatable pattern before difficulty goes up.",
            }

        monkeypatch.setattr(service, "_call_claude_json", fake_claude)

        response = service.generate_one_on_one_prep(
            db,
            rep=rep,
            manager=manager,
            period_days=14,
        )

        assert response.rep_id == rep.id
        assert response.manager_id == manager.id
        assert captured["system_prompt"].startswith(
            "Coaching prefix from prompt version.\n\n"
        )
        assert "You are a precise manager prep copilot. Return only valid JSON." in captured["system_prompt"]
    finally:
        db.close()
