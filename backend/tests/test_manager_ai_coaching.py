from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api import manager as manager_api
from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.types import AssignmentStatus, SessionStatus, TurnSpeaker
from app.schemas.ai_meta import AiMeta
from app.schemas.knowledge import RetrievedChunk
from app.schemas.manager_ai import ManagerChatAnswerContent, ManagerChatClassification, TeamCoachingSummaryContent
from app.services.document_retrieval_service import DocumentRetrievalService
from app.services.manager_ai_coaching_service import AiCoachingUnavailableError
from app.services.provider_clients import JsonLlmAttempt, JsonLlmResult


@pytest.fixture(autouse=True)
def clear_ai_caches() -> None:
    manager_api.manager_ai_service.company_training_context_cache.clear()
    manager_api.manager_ai_service.rep_insight_cache.clear()
    manager_api.manager_ai_service.session_annotations_cache.clear()


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def _ai_result(payload, *, provider: str = "openai", model: str = "gpt-4o-mini", status: str = "live", fallback_used: bool = False, task: str = "test") -> JsonLlmResult:
    return JsonLlmResult(
        payload=payload,
        provider=provider,
        model=model,
        real_call=provider != "mock",
        latency_ms=42,
        fallback_used=fallback_used,
        attempts=[
            JsonLlmAttempt(
                provider=provider,
                model=model,
                outcome="success",
                latency_ms=42,
                real_call=provider != "mock",
                task=task,
            )
        ],
        status=status,
    )


def _ai_meta(task: str = "test") -> AiMeta:
    return manager_api.manager_ai_service._ai_meta_from_result(
        _ai_result({"ok": True}, task=task),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _create_scored_session(
    seed_org: dict[str, str],
    *,
    day_offset: int,
    overall_score: float,
    weakness_tags: list[str],
    ai_summary: str,
) -> dict[str, str]:
    db = SessionLocal()
    started_at = datetime.now(timezone.utc) - timedelta(days=day_offset)

    assignment = Assignment(
        scenario_id=seed_org["scenario_id"],
        rep_id=seed_org["rep_id"],
        assigned_by=seed_org["manager_id"],
        status=AssignmentStatus.COMPLETED,
        retry_policy={"max_attempts": 2},
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
        text="Hi, I can help cut your pest bill without locking you into a long contract.",
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=12),
        objection_tags=[],
    )
    ai_turn = SessionTurn(
        session_id=session.id,
        turn_index=2,
        speaker=TurnSpeaker.AI,
        stage="objection_handling",
        text="I already have someone and I do not want to spend more money.",
        started_at=started_at + timedelta(seconds=14),
        ended_at=started_at + timedelta(seconds=26),
        objection_tags=["price"],
    )
    db.add_all([rep_turn, ai_turn])
    db.flush()

    scorecard = Scorecard(
        session_id=session.id,
        overall_score=overall_score,
        category_scores={
            "opening": {"score": 7.2, "rationale": "Good opener", "evidence_turn_ids": [rep_turn.id]},
            "pitch_delivery": {"score": 6.4, "rationale": "Pitch was soft", "evidence_turn_ids": [rep_turn.id]},
            "objection_handling": {"score": 5.1, "rationale": "Price objection wobble", "evidence_turn_ids": [rep_turn.id]},
            "closing_technique": {"score": 6.0, "rationale": "Did not ask for the next step", "evidence_turn_ids": [rep_turn.id]},
            "professionalism": {"score": 7.6, "rationale": "Calm tone", "evidence_turn_ids": [rep_turn.id]},
        },
        highlights=[
            {"type": "strong", "note": "Started with a concise value prop", "turn_id": rep_turn.id},
            {"type": "improve", "note": "Validated the price concern too early", "turn_id": rep_turn.id},
        ],
        ai_summary=ai_summary,
        evidence_turn_ids=[rep_turn.id],
        weakness_tags=weakness_tags,
    )
    db.add(scorecard)
    db.commit()

    payload = {
        "session_id": session.id,
        "scorecard_id": scorecard.id,
        "rep_turn_id": rep_turn.id,
        "ai_turn_id": ai_turn.id,
    }
    db.close()
    return payload


def test_ai_rep_insight_endpoint_caches_by_rep_and_period(client, seed_org, monkeypatch):
    _create_scored_session(
        seed_org,
        day_offset=2,
        overall_score=5.8,
        weakness_tags=["objection_handling", "price", "objection_handling"],
        ai_summary="Handled the opener well but caved when price came up.",
    )
    _create_scored_session(
        seed_org,
        day_offset=5,
        overall_score=6.4,
        weakness_tags=["objection_handling", "closing"],
        ai_summary="Built light rapport, then lost momentum on the first objection.",
    )
    _create_scored_session(
        seed_org,
        day_offset=8,
        overall_score=6.9,
        weakness_tags=["price", "closing"],
        ai_summary="More confident pace, but the close still lacked urgency.",
    )

    call_count = {"value": 0}

    def fake_manager_call(*, system_prompt: str, user_prompt: str, max_tokens: int, task: str, fast: bool = False, validator=None):
        call_count["value"] += 1
        assert "Ray Rep" in user_prompt
        payload = {
            "headline": "Ray loses leverage on price objections",
            "primary_weakness": "Objection Handling",
            "root_cause": "Ray does not pivot with a memorized bridge. That causes him to concede too early.",
            "drill_recommendation": 'Assign "Skeptical Homeowner" difficulty 3',
            "coaching_script": "Ray, acknowledge the concern, then pivot to value. Ask a clarifying question before defending price. Practice the bridge until it sounds natural.",
            "expected_improvement": "+1.0 on objection handling within 4 sessions",
        }
        return _ai_result(validator(payload) if validator else payload, task=task)

    monkeypatch.setattr(manager_api.manager_ai_service, "_call_manager_ai_json", fake_manager_call)

    response = client.post(
        "/manager/ai/rep-insight",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "rep_id": seed_org["rep_id"], "period_days": 30},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rep_id"] == seed_org["rep_id"]
    assert body["rep_name"] == "Ray Rep"
    assert body["headline"] == "Ray loses leverage on price objections"
    assert body["data_summary"]["session_count"] == 3
    assert body["data_summary"]["top_weakness_tags"][0] == "objection_handling"

    cached = client.post(
        "/manager/ai/rep-insight",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "rep_id": seed_org["rep_id"], "period_days": 30},
    )
    assert cached.status_code == 200
    assert cached.json()["headline"] == body["headline"]
    assert cached.json()["ai_meta"]["status"] == "cached"
    assert cached.json()["ai_meta"]["cached"] is True
    assert call_count["value"] == 1


def test_ai_session_annotations_endpoint_caches_and_sorts_by_turn(client, seed_org, monkeypatch):
    session_data = _create_scored_session(
        seed_org,
        day_offset=1,
        overall_score=5.9,
        weakness_tags=["objection_handling", "price"],
        ai_summary="Promising opener, weak pivot on price.",
    )

    call_count = {"value": 0}

    def fake_manager_call(*, system_prompt: str, user_prompt: str, max_tokens: int, task: str, fast: bool = False, validator=None):
        call_count["value"] += 1
        assert session_data["rep_turn_id"] in user_prompt
        payload = [
            {
                "turn_id": session_data["ai_turn_id"],
                "type": "weakness",
                "label": "Price objection wobble",
                "explanation": "The rep allowed the price objection to control the frame. That weakened the rest of the exchange.",
                "coaching_tip": "Acknowledge briefly, then pivot to long-term value.",
            },
            {
                "turn_id": session_data["rep_turn_id"],
                "type": "strength",
                "label": "Crisp opener",
                "explanation": "The rep led with a clear promise. That bought a few extra seconds of attention.",
                "coaching_tip": None,
            },
        ]
        return _ai_result(validator(payload) if validator else payload, task=task)

    monkeypatch.setattr(manager_api.manager_ai_service, "_call_manager_ai_json", fake_manager_call)

    response = client.post(
        "/manager/ai/session-annotations",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "session_id": session_data["session_id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_data["session_id"]
    assert [item["turn_id"] for item in body["annotations"]] == [
        session_data["rep_turn_id"],
        session_data["ai_turn_id"],
    ]

    cached = client.post(
        "/manager/ai/session-annotations",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "session_id": session_data["session_id"]},
    )
    assert cached.status_code == 200
    assert cached.json()["annotations"] == body["annotations"]
    assert cached.json()["ai_meta"]["status"] == "cached"
    assert call_count["value"] == 1


def test_ai_team_coaching_summary_endpoint_returns_summary(client, seed_org, monkeypatch):
    def fake_analytics(*args, **kwargs):
        return {
            "summary": {
                "coaching_note_count": 6,
                "review_count": 8,
                "override_rate": 0.25,
                "average_override_delta": 0.6,
                "retry_uplift_avg": 1.1,
                "coached_retry_uplift_avg": 1.7,
                "intervention_improved_rate": 0.66,
                "calibration_drift_score": 0.42,
            },
            "weakness_tag_uplift": [{"tag": "objection_handling", "delta": 1.2, "sample_size": 4}],
            "coaching_uplift": [{"rep_name": "Ray Rep", "delta": 1.8, "outcome": "improved", "visible_to_rep": True}],
            "manager_calibration": [{"reviewer_name": "Mia Manager", "average_override_delta": 0.6, "absolute_average_delta": 0.6}],
            "recent_notes": [{"rep_name": "Ray Rep", "weakness_tags": ["objection_handling"], "note": "Use the bridge sooner", "delta": 1.2}],
            "retry_impact": [{"rep_name": "Ray Rep", "delta": 1.4}],
        }

    monkeypatch.setattr(manager_api.management_analytics_service, "get_coaching_analytics", fake_analytics)
    monkeypatch.setattr(
        manager_api.manager_ai_service,
        "_call_manager_ai_json",
        lambda **kwargs: _ai_result(
            TeamCoachingSummaryContent.model_validate(
                {
                    "summary": "Objection handling is still the main coaching gap across the team. Visible-to-rep coaching notes are producing the strongest lift for Ray Rep and similar retry cases. This week, tighten calibration discipline while assigning one more objection-focused retry block."
                }
            ),
            task=kwargs.get("task", "test"),
        ),
    )

    response = client.post(
        "/manager/ai/team-coaching-summary",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "period_days": 30},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manager_id"] == seed_org["manager_id"]
    assert "Objection handling is still the main coaching gap" in body["summary"]
    assert body["data_summary"]["summary"]["coaching_note_count"] == 6


def test_company_training_context_reuses_cached_retrieval(seed_org, monkeypatch):
    call_count = {"value": 0}

    def fake_retrieve_for_topic(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
        call_count["value"] += 1
        assert org_id == seed_org["org_id"]
        return [
            RetrievedChunk(
                chunk_id="chunk-manager-cache-1",
                document_id="document-manager-cache-1",
                document_name="Closing Playbook",
                text="Use a low-pressure next step and confirm homeowner concerns before asking for commitment.",
                similarity_score=0.95,
            )
        ]

    monkeypatch.setattr(DocumentRetrievalService, "retrieve_for_topic", fake_retrieve_for_topic)

    db = SessionLocal()
    try:
        first = manager_api.manager_ai_service._get_company_training_context(
            db,
            org_id=seed_org["org_id"],
            topic="coaching closing technique improvement",
            context_hint="rep Ray Rep weak areas closing",
            k=3,
            min_score=0.68,
            max_tokens=900,
        )
        second = manager_api.manager_ai_service._get_company_training_context(
            db,
            org_id=seed_org["org_id"],
            topic="coaching closing technique improvement",
            context_hint="rep Ray Rep weak areas closing",
            k=3,
            min_score=0.68,
            max_tokens=900,
        )
    finally:
        db.close()

    assert call_count["value"] == 1
    assert first == second
    assert first is not None
    assert "Closing Playbook" in first


def test_ai_endpoints_return_503_when_claude_is_unavailable(client, seed_org, monkeypatch):
    session_data = _create_scored_session(
        seed_org,
        day_offset=1,
        overall_score=5.7,
        weakness_tags=["objection_handling"],
        ai_summary="Needed a stronger objection pivot.",
    )

    def raise_unavailable(**kwargs):
        raise AiCoachingUnavailableError("Claude analysis is temporarily unavailable")

    monkeypatch.setattr(manager_api.manager_ai_service, "_call_manager_ai_json", raise_unavailable)
    monkeypatch.setattr(
        manager_api.management_analytics_service,
        "get_coaching_analytics",
        lambda *args, **kwargs: {"summary": {}, "weakness_tag_uplift": [], "coaching_uplift": [], "manager_calibration": [], "recent_notes": [], "retry_impact": []},
    )

    rep_response = client.post(
        "/manager/ai/rep-insight",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "rep_id": seed_org["rep_id"], "period_days": 30},
    )
    assert rep_response.status_code == 503
    assert "temporarily unavailable" in rep_response.json()["detail"]["message"]

    annotations_response = client.post(
        "/manager/ai/session-annotations",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "session_id": session_data["session_id"]},
    )
    assert annotations_response.status_code == 503
    assert "temporarily unavailable" in annotations_response.json()["detail"]["message"]

    summary_response = client.post(
        "/manager/ai/team-coaching-summary",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "period_days": 30},
    )
    assert summary_response.status_code == 404
    assert "no coaching data" in summary_response.json()["detail"]["message"].lower()

    chat_response = client.post(
        "/manager/ai/chat",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "message": "Who needs coaching help?", "period_days": 30},
    )
    assert chat_response.status_code == 503
    assert "temporarily unavailable" in chat_response.json()["detail"]["message"]


def test_manager_ai_chat_uses_command_center_for_team_questions(client, seed_org, monkeypatch):
    _create_scored_session(
        seed_org,
        day_offset=2,
        overall_score=6.8,
        weakness_tags=["objection_handling"],
        ai_summary="Objection handling remains the main drag.",
    )

    monkeypatch.setattr(
        manager_api.manager_ai_service,
        "classify_manager_chat_intent_with_meta",
        lambda **kwargs: (
            ManagerChatClassification(
                intent="team_performance",
                rep_name_mentioned=None,
                scenario_mentioned=None,
                category_mentioned=None,
            ),
            _ai_meta("classification"),
        ),
    )
    monkeypatch.setattr(
        manager_api.management_analytics_service,
        "get_command_center",
        lambda *args, **kwargs: {
            "summary": {"team_average_score": 6.8, "reps_at_risk": 2},
            "weakest_categories": [{"category": "objection_handling", "average_score": 5.4}],
        },
    )

    def fake_answer_manager_chat(*, period_days, message, conversation_history, relevant_data):
        assert period_days == 30
        assert message == "How is my team doing?"
        assert conversation_history == [{"role": "user", "content": "Give me the latest summary."}]
        assert relevant_data["command_center"]["summary"]["team_average_score"] == 6.8
        return (
            ManagerChatAnswerContent(
                answer="Your team is averaging 6.8 with objection handling as the main drag.",
                key_metric="6.8",
                key_metric_label="Team Average Score",
                follow_up_suggestions=["Who is dragging the average down?", "What scenario is hurting pass rate?"],
                action_suggestion="Open Command Center and review the lowest objection-handling cluster.",
                data_points=[{"label": "At Risk", "value": "2 reps"}],
            ),
            _ai_meta("answer"),
        )

    monkeypatch.setattr(manager_api.manager_ai_service, "answer_manager_chat_with_meta", fake_answer_manager_chat)

    response = client.post(
        "/manager/ai/chat",
        headers=_manager_headers(seed_org),
        json={
            "manager_id": seed_org["manager_id"],
            "message": "How is my team doing?",
            "conversation_history": [{"role": "user", "content": "Give me the latest summary."}],
            "period_days": 30,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent_detected"] == "team_performance"
    assert body["sources_used"] == ["command_center"]
    assert body["key_metric"] == "6.8"
    assert body["data_points"][0]["value"] == "2 reps"
    assert body["ai_meta"]["status"] == "live"


def test_manager_ai_chat_returns_truthful_no_data_response_for_empty_team_window(client, seed_org, monkeypatch):
    monkeypatch.setattr(
        manager_api.manager_ai_service,
        "classify_manager_chat_intent_with_meta",
        lambda **kwargs: (
            ManagerChatClassification(
                intent="team_performance",
                rep_name_mentioned=None,
                scenario_mentioned=None,
                category_mentioned=None,
            ),
            _ai_meta("classification"),
        ),
    )
    monkeypatch.setattr(
        manager_api.manager_ai_service,
        "answer_manager_chat_with_meta",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run for no-data chat")),
    )

    response = client.post(
        "/manager/ai/chat",
        headers=_manager_headers(seed_org),
        json={
            "manager_id": seed_org["manager_id"],
            "message": "How is my team doing?",
            "conversation_history": [],
            "period_days": 30,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ai_meta"]["status"] == "no_data"
    assert body["sources_used"] == []
    assert body["key_metric"] is None
    assert body["data_points"] == []
    assert body["data_state"] in {"no_assignments", "no_sessions", "no_scored_sessions"}


def test_manager_ai_chat_uses_rep_progress_for_rep_specific_questions(client, seed_org, monkeypatch):
    _create_scored_session(
        seed_org,
        day_offset=2,
        overall_score=6.4,
        weakness_tags=["closing"],
        ai_summary="Steady opener, but the close stalled out.",
    )

    monkeypatch.setattr(
        manager_api.manager_ai_service,
        "classify_manager_chat_intent_with_meta",
        lambda **kwargs: (
            ManagerChatClassification(
                intent="rep_specific",
                rep_name_mentioned="Ray",
                scenario_mentioned=None,
                category_mentioned="closing",
            ),
            _ai_meta("classification"),
        ),
    )

    def fake_answer_manager_chat(*, relevant_data, **kwargs):
        rep_key = f"rep_progress:{seed_org['rep_id']}"
        assert relevant_data["resolved_rep"]["rep_id"] == seed_org["rep_id"]
        assert rep_key in relevant_data
        assert relevant_data[rep_key]["rep_name"] == "Ray Rep"
        return (
            ManagerChatAnswerContent(
                answer="Ray is stable overall, but closing is still his lowest category this month.",
                key_metric="6.4",
                key_metric_label="Ray Average Score",
                follow_up_suggestions=["Should I assign a follow-up drill?", "How does Ray compare to the team?"],
                action_suggestion="Open Ray's rep page and assign a closing-focused retry.",
                data_points=[{"label": "Weak Area", "value": "closing"}],
            ),
            _ai_meta("answer"),
        )

    monkeypatch.setattr(manager_api.manager_ai_service, "answer_manager_chat_with_meta", fake_answer_manager_chat)

    response = client.post(
        "/manager/ai/chat",
        headers=_manager_headers(seed_org),
        json={"manager_id": seed_org["manager_id"], "message": "How is Ray doing on closing?", "period_days": 30},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent_detected"] == "rep_specific"
    assert body["sources_used"] == [f"rep_progress:{seed_org['rep_id']}"]
    assert body["key_metric_label"] == "Ray Average Score"
