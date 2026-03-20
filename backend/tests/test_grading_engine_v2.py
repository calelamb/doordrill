import time
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.grading import GradingRun
from app.models.scorecard import Scorecard
from app.schemas.scorecard import StructuredScorecardPayloadV2
from app.services.grading_service import GradingPromptBuilder, GradingService
from app.services.session_postprocess_service import SessionPostprocessService


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


def _await_session_ended(ws) -> None:
    for _ in range(80):
        message = ws.receive_json()
        if message["type"] == "server.session.state" and message["payload"].get("state") == "ended":
            return
    raise AssertionError("session did not emit ended state")


def _run_session(
    client,
    seed_org: dict[str, str],
    assignment_id: str,
    transcript_hint: str,
    *,
    scenario_id: str | None = None,
) -> str:
    session = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": scenario_id or seed_org["scenario_id"],
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
        _await_session_ended(ws)

    return session_id


def _await_scorecard_and_run(session_id: str) -> tuple[Scorecard, GradingRun]:
    scorecard = None
    grading_run = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
            grading_run = db.scalar(
                select(GradingRun)
                .where(GradingRun.session_id == session_id)
                .order_by(GradingRun.created_at.desc())
            )
        finally:
            db.close()
        if scorecard is not None and grading_run is not None:
            break
        time.sleep(0.1)

    assert scorecard is not None, f"scorecard was not created for session {session_id} within 60 seconds"
    assert grading_run is not None, f"grading run was not created for session {session_id} within 60 seconds"
    return scorecard, grading_run


def _turn(
    turn_id: str,
    *,
    speaker: str = "rep",
    stage: str = "objection_handling",
    text: str = "test",
    behavioral_signals: list[str] | None = None,
    objection_tags: list[str] | None = None,
):
    return SimpleNamespace(
        id=turn_id,
        turn_index=int(turn_id.split("-")[-1]) if "-" in turn_id and turn_id.split("-")[-1].isdigit() else 1,
        speaker=SimpleNamespace(value=speaker),
        stage=stage,
        text=text,
        behavioral_signals=list(behavioral_signals or []),
        mb_behaviors=[],
        objection_tags=list(objection_tags or []),
    )


def _session(turns: list[SimpleNamespace]):
    return SimpleNamespace(turns=turns)


def _llm_payload(turn_id: str) -> dict:
    return {
        "category_scores": {
            key: {
                "score": 7.5,
                "confidence": 0.9,
                "rationale_summary": "solid",
                "rationale_detail": "solid detail",
                "evidence_turn_ids": [turn_id],
                "behavioral_signals": [],
                "improvement_target": None,
            }
            for key in ("opening", "pitch_delivery", "objection_handling", "closing_technique", "professionalism")
        },
        "overall_score": 7.5,
        "highlights": [
            {"type": "strong", "note": "Strong opener", "turn_id": turn_id},
            {"type": "improve", "note": "Could tighten close", "turn_id": turn_id},
        ],
        "ai_summary": "You opened with enough control to keep the conversation moving. Turn 1 set the tone, but the follow-up still needed more precision. Next time, make the next step more direct after you answer the concern.",
        "weakness_tags": [],
        "evidence_quality": "moderate",
        "session_complexity": 2,
    }


def test_grading_prompt_builder_includes_context_blocks():
    turns = [
        SimpleNamespace(
            turn_index=1,
            id="turn-1",
            speaker=SimpleNamespace(value="rep"),
            stage="initial_pitch",
            text="Can we get you scheduled today?",
        )
    ]

    prompt = GradingPromptBuilder().build(
        turns,
        session_context={
            "difficulty": 5,
            "emotion_trajectory": ["hostile", "annoyed", "curious"],
            "peak_resistance": 5,
            "objections_resolved": ["price", "trust"],
            "total_rep_turns": 3,
        },
        first_turn_signals=["pushes_close"],
        inflection_points=[
            {
                "turn_index": 1,
                "direction": "negative",
                "coaching_label": "Lost them here",
                "coaching_note": "Rep pushed for a close before earning trust - homeowner hardened.",
            }
        ],
    )

    assert "SESSION CONTEXT (use this to calibrate scores):" in prompt
    assert "OPENING QUALITY: damaging opener" in prompt
    assert "KEY MOMENTS IN THIS SESSION" in prompt
    assert "SCORING RUBRICS -" in prompt


def test_grading_prompt_builder_marks_strong_openers():
    turns = [
        SimpleNamespace(
            turn_index=1,
            id="turn-1",
            speaker=SimpleNamespace(value="rep"),
            stage="initial_pitch",
            text="A few of your neighbors nearby had us out this week.",
        )
    ]

    prompt = GradingPromptBuilder().build(
        turns,
        first_turn_signals=["builds_rapport", "mentions_social_proof"],
    )

    assert "OPENING QUALITY: strong opener" in prompt


def test_grading_prompt_builder_includes_calibration_language():
    prompt = GradingPromptBuilder().build([
        _turn("rep-1", stage="initial_pitch", text="Hi, I'm Alex with Acme.", behavioral_signals=["builds_rapport"])
    ])

    assert "Use the full 0-10 range" in prompt
    assert "SCORE CALIBRATION:" in prompt


def test_fallback_opening_score_is_low_for_hard_close_opening():
    service = GradingService()
    rep_turns = [
        _turn(
            "rep-1",
            stage="initial_pitch",
            text="Can we get you signed up right now?",
            behavioral_signals=["pushes_close"],
        )
    ]

    grading = service._grade_with_fallback(
        session=_session(rep_turns),
        rep_turns=rep_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["pushes_close"],
        inflection_points=[],
    )

    assert grading["category_scores"]["opening"]["score"] <= 4.0


def test_fallback_opening_score_is_high_for_perfect_opening():
    service = GradingService()
    rep_turns = [
        _turn(
            "rep-1",
            stage="initial_pitch",
            text="Hi, I'm Alex with Acme - we were helping a few of your neighbors nearby this week.",
            behavioral_signals=["builds_rapport", "mentions_social_proof"],
        )
    ]

    grading = service._grade_with_fallback(
        session=_session(rep_turns),
        rep_turns=rep_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["builds_rapport", "mentions_social_proof"],
        inflection_points=[],
    )

    assert grading["category_scores"]["opening"]["score"] >= 9.0


def test_fallback_batch_scores_span_at_least_three_points():
    service = GradingService()
    sessions = [
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["pushes_close", "neutral_delivery"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["ignores_objection", "dismisses_concern"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["pushes_close"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["neutral_delivery"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["neutral_delivery"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["pushes_close"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["invites_dialogue"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport", "mentions_social_proof"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern", "explains_value"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["invites_dialogue", "reduces_pressure"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport", "mentions_social_proof"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern", "provides_proof", "reduces_pressure"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["invites_dialogue", "reduces_pressure"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport", "mentions_social_proof", "explains_value"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern", "explains_value", "provides_proof"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["invites_dialogue", "reduces_pressure"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["neutral_delivery"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["ignores_objection"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["pushes_close"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern", "explains_value", "reduces_pressure"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["invites_dialogue"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport", "mentions_social_proof"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["dismisses_concern"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["pushes_close"]),
        ],
        [
            _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport", "mentions_social_proof", "explains_value"]),
            _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern", "explains_value", "provides_proof", "reduces_pressure"]),
            _turn("rep-3", stage="close_attempt", behavioral_signals=["invites_dialogue", "reduces_pressure"]),
        ],
    ]

    scores = []
    for turns in sessions:
        grading = service._grade_with_fallback(
            session=_session(turns),
            rep_turns=turns,
            ai_turns=[],
            session_context={},
            first_turn_signals=list(turns[0].behavioral_signals),
            inflection_points=[],
        )
        scores.append(grading["overall_score"])

    assert max(scores) - min(scores) >= 3.0


def test_fallback_scores_poor_objection_handling_from_negative_signals():
    service = GradingService()
    rep_turns = [
        _turn(
            "rep-1",
            text="Can we just get this scheduled today?",
            behavioral_signals=["pushes_close", "ignores_objection"],
        ),
        _turn(
            "rep-2",
            text="You should just trust me and move forward.",
            behavioral_signals=["pushes_close", "ignores_objection"],
        ),
    ]

    grading = service._grade_with_fallback(
        session=_session(rep_turns),
        rep_turns=rep_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["pushes_close"],
        inflection_points=[],
    )

    assert grading["category_scores"]["objection_handling"]["score"] <= 4.0


def test_fallback_scores_strong_objection_handling_from_positive_signals():
    service = GradingService()
    rep_turns = [
        _turn(
            "rep-1",
            text="I understand the concern and can explain the value clearly.",
            behavioral_signals=["acknowledges_concern", "explains_value"],
        ),
        _turn(
            "rep-2",
            text="Let me show proof and keep this low pressure.",
            behavioral_signals=["acknowledges_concern", "explains_value", "provides_proof", "reduces_pressure"],
        ),
    ]

    grading = service._grade_with_fallback(
        session=_session(rep_turns),
        rep_turns=rep_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["acknowledges_concern", "explains_value"],
        inflection_points=[],
    )

    assert grading["category_scores"]["objection_handling"]["score"] >= 7.5


def test_fallback_scores_do_not_change_from_session_length_alone():
    service = GradingService()
    short_turns = [_turn("rep-1", stage="initial_pitch", text="I am in the area.", behavioral_signals=["neutral_delivery"])]
    long_turns = [
        _turn(f"rep-{index}", stage="initial_pitch", text="I am in the area.", behavioral_signals=["neutral_delivery"])
        for index in range(1, 6)
    ]

    short_grading = service._grade_with_fallback(
        session=_session(short_turns),
        rep_turns=short_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["neutral_delivery"],
        inflection_points=[],
    )
    long_grading = service._grade_with_fallback(
        session=_session(long_turns),
        rep_turns=long_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["neutral_delivery"],
        inflection_points=[],
    )

    assert short_grading["category_scores"]["opening"]["score"] == long_grading["category_scores"]["opening"]["score"]


def test_fallback_weakness_tags_fire_from_repeated_negative_signals():
    service = GradingService()
    rep_turns = [
        _turn("rep-1", behavioral_signals=["ignores_objection", "pushes_close"]),
        _turn("rep-2", behavioral_signals=["ignores_objection", "pushes_close"]),
    ]

    grading = service._grade_with_fallback(
        session=_session(rep_turns),
        rep_turns=rep_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["pushes_close"],
        inflection_points=[],
    )

    assert "objection_handling" in grading["weakness_tags"]
    assert "closing_technique" in grading["weakness_tags"]


def test_normalized_grading_adds_signal_based_weakness_tags_even_with_high_scores():
    service = GradingService()
    rep_turns = [
        _turn("rep-1", behavioral_signals=["ignores_objection"]),
        _turn("rep-2", behavioral_signals=["ignores_objection"]),
    ]
    payload = {
        "overall_score": 7.8,
        "category_scores": {
            key: {
                "score": 7.5,
                "confidence": 0.9,
                "rationale_summary": "solid",
                "rationale_detail": "solid detail",
                "evidence_turn_ids": [rep_turns[0].id],
                "behavioral_signals": [],
                "improvement_target": None,
            }
            for key in ("opening", "pitch_delivery", "objection_handling", "closing_technique", "professionalism")
        },
        "highlights": [
            {"type": "strong", "note": "Strong opener", "turn_id": rep_turns[0].id},
            {"type": "improve", "note": "Could tighten close", "turn_id": rep_turns[1].id},
        ],
        "ai_summary": "You did several things well and should keep improving your close.",
        "weakness_tags": [],
        "evidence_quality": "moderate",
        "session_complexity": 2,
    }

    normalized = service._normalize_grading(
        payload,
        session=_session(rep_turns),
        first_turn_signals=[],
        inflection_points=[],
    )

    assert "objection_handling" in normalized["weakness_tags"]


def test_clean_rep_with_strong_scores_has_no_weakness_tags():
    service = GradingService()
    rep_turns = [
        _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport", "mentions_social_proof"]),
        _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern", "explains_value", "provides_proof"]),
        _turn("rep-3", stage="close_attempt", behavioral_signals=["invites_dialogue", "reduces_pressure"]),
    ]
    category_scores = {
        key: {"score": 7.5}
        for key in ("opening", "pitch_delivery", "objection_handling", "closing_technique", "professionalism")
    }

    weakness_tags = service._derive_weakness_tags(category_scores=category_scores, rep_turns=rep_turns)

    assert weakness_tags == []


def test_scorecard_schema_allows_700_char_ai_summary():
    field = StructuredScorecardPayloadV2.model_fields["ai_summary"]

    assert field.metadata[1].max_length == 700


def test_grading_prompt_includes_three_part_ai_summary_instruction():
    prompt = GradingPromptBuilder().build([
        _turn("rep-1", stage="initial_pitch", text="Hi, I'm Alex with Acme.", behavioral_signals=["builds_rapport"])
    ])

    assert "ai_summary format (max 700 chars" in prompt
    assert "Sentence 1: What the rep did well" in prompt
    assert "Sentence 2: The moment things shifted" in prompt
    assert "Sentence 3: The one concrete fix" in prompt


def test_normalized_grading_clips_ai_summary_to_700_chars():
    service = GradingService()
    rep_turns = [
        _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport"]),
        _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern"]),
    ]
    payload = {
        "overall_score": 7.8,
        "category_scores": {
            key: {
                "score": 7.5,
                "confidence": 0.9,
                "rationale_summary": "solid",
                "rationale_detail": "solid detail",
                "evidence_turn_ids": [rep_turns[0].id],
                "behavioral_signals": [],
                "improvement_target": None,
            }
            for key in ("opening", "pitch_delivery", "objection_handling", "closing_technique", "professionalism")
        },
        "highlights": [
            {"type": "strong", "note": "Strong opener", "turn_id": rep_turns[0].id},
            {"type": "improve", "note": "Could tighten close", "turn_id": rep_turns[1].id},
        ],
        "ai_summary": "x" * 900,
        "weakness_tags": [],
        "evidence_quality": "moderate",
        "session_complexity": 2,
    }

    normalized = service._normalize_grading(
        payload,
        session=_session(rep_turns),
        first_turn_signals=[],
        inflection_points=[],
    )

    assert len(normalized["ai_summary"]) == 700


def test_fallback_ai_summary_uses_three_sentence_coaching_shape():
    service = GradingService()
    rep_turns = [
        _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport"]),
        _turn("rep-2", stage="objection_handling", behavioral_signals=["acknowledges_concern", "explains_value"]),
        _turn("rep-3", stage="close_attempt", behavioral_signals=["pushes_close"]),
    ]

    grading = service._grade_with_fallback(
        session=_session(rep_turns),
        rep_turns=rep_turns,
        ai_turns=[],
        session_context={},
        first_turn_signals=["builds_rapport"],
        inflection_points=[],
    )

    assert grading["ai_summary"].count(".") >= 3


@pytest.mark.asyncio
async def test_grade_with_llm_uses_grading_model_and_timeout(monkeypatch):
    service = GradingService()
    service.settings.openai_api_key = "test-key"
    service.settings.grading_model = "gpt-4o-mini"
    service.settings.grading_timeout_seconds = 20.0
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    captured: dict[str, object] = {}
    rep_turn = _turn("rep-1", stage="initial_pitch", behavioral_signals=["builds_rapport"])

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": __import__("json").dumps(_llm_payload(rep_turn.id))}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["model"] = json["model"]
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = await service._grade_with_llm(
        session=_session([rep_turn]),
        prompt_template="test prompt",
        turns=[rep_turn],
        session_context={},
        first_turn_signals=["builds_rapport"],
        inflection_points=[],
    )

    assert captured["model"] == "gpt-4o-mini"
    assert captured["timeout"] == 20.0
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_grade_with_llm_timeout_uses_fallback_and_requests_retry(monkeypatch):
    service = GradingService()
    service.settings.openai_api_key = "test-key"
    service.settings.grading_timeout_seconds = 20.0
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    rep_turn = _turn("rep-1", stage="objection_handling", behavioral_signals=["acknowledges_concern", "explains_value"])

    class TimeoutAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", TimeoutAsyncClient)

    result = await service._grade_with_llm(
        session=_session([rep_turn]),
        prompt_template="test prompt",
        turns=[rep_turn],
        session_context={},
        first_turn_signals=[],
        inflection_points=[],
    )

    assert result["status"] == "timeout_fallback"
    assert result["retry_requested"] is True


@pytest.mark.asyncio
async def test_postprocess_enqueue_or_run_uses_background_mode_without_celery(monkeypatch):
    service = SessionPostprocessService()
    service.settings.use_celery = False
    scheduled: list[str] = []

    class FakeDb:
        def commit(self):
            return None

    def fake_ensure_run_row(_db, *, session_id: str, task_type: str):
        return SimpleNamespace(status="pending", next_retry_at=None)

    class FakeTask:
        def add_done_callback(self, *_args, **_kwargs):
            return None

    def fake_create_task(coro):
        scheduled.append("started")
        coro.close()
        return FakeTask()

    monkeypatch.setattr(service, "_ensure_run_row", fake_ensure_run_row)
    monkeypatch.setattr("app.services.session_postprocess_service.asyncio.create_task", fake_create_task)

    result = await service.enqueue_or_run(FakeDb(), "session-123")

    assert result["mode"] == "background"
    assert scheduled == ["started"]


def test_select_grading_turns_trims_long_sessions_and_keeps_priority_turns():
    service = GradingService()
    turns = []
    for index in range(1, 31):
        stage = "initial_pitch"
        objection_tags = []
        if 6 <= index <= 18:
            stage = "objection_handling"
            objection_tags = ["price"] if index % 2 == 0 else []
        if 22 <= index <= 26:
            stage = "close_attempt"
        turns.append(
            _turn(
                f"rep-{index}",
                stage=stage,
                text=f"turn {index}",
                behavioral_signals=["neutral_delivery"],
                objection_tags=objection_tags,
            )
        )

    selected = service._select_grading_turns(turns)
    selected_ids = [turn.id for turn in selected]

    assert len(selected) <= 20
    assert {"rep-1", "rep-2", "rep-29", "rep-30"}.issubset(set(selected_ids))
    assert any(turn.stage == "objection_handling" for turn in selected[2:-2])
    assert any(turn.stage == "close_attempt" for turn in selected[2:-2])
