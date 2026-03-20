from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.session import SessionTurn
from app.models.training import ConversationQualitySignal
from app.models.types import TurnSpeaker
from app.services.conversation_realism_eval_service import ConversationRealismEvalService


def _make_turn_pair(
    *,
    rep_text: str,
    ai_text: str,
    response_plan: dict,
    turn_analysis: dict | None = None,
    transcript_quality: dict | None = None,
    interrupted: bool = False,
) -> tuple[list[SessionTurn], list[dict]]:
    started_at = datetime.now(timezone.utc)
    rep_turn = SessionTurn(
        id="rep-turn",
        session_id="session-eval",
        turn_index=1,
        speaker=TurnSpeaker.REP,
        stage="objection_handling",
        text=rep_text,
        normalized_transcript_text=rep_text,
        transcript_confidence=0.98,
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=4),
    )
    ai_turn = SessionTurn(
        id="ai-turn",
        session_id="session-eval",
        turn_index=2,
        speaker=TurnSpeaker.AI,
        stage="objection_handling",
        text=ai_text,
        emotion_before="skeptical",
        emotion_after="skeptical",
        started_at=started_at + timedelta(seconds=4),
        ended_at=started_at + timedelta(seconds=8),
    )
    committed_payloads = [
        {
            "ai_turn_id": ai_turn.id,
            "response_plan": response_plan,
            "turn_analysis": turn_analysis or {},
            "transcript_quality": transcript_quality or {"confidence": 0.98, "applied_terms": ["Acme Pest Control"]},
            "interrupted": interrupted,
        }
    ]
    return [rep_turn, ai_turn], committed_payloads


def test_realism_eval_flags_over_softening_and_repetition():
    service = ConversationRealismEvalService()
    started_at = datetime.now(timezone.utc)
    turns = [
        SessionTurn(
            id="rep-1",
            session_id="session-1",
            turn_index=1,
            speaker=TurnSpeaker.REP,
            stage="close_attempt",
            text="Can we get you on the schedule today?",
            normalized_transcript_text="Can we get you on the schedule today?",
            transcript_confidence=0.96,
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=4),
        ),
        SessionTurn(
            id="ai-1",
            session_id="session-1",
            turn_index=2,
            speaker=TurnSpeaker.AI,
            stage="close_attempt",
            text="Sounds good, let's do it today.",
            emotion_before="skeptical",
            emotion_after="skeptical",
            started_at=started_at + timedelta(seconds=4),
            ended_at=started_at + timedelta(seconds=8),
        ),
        SessionTurn(
            id="rep-2",
            session_id="session-1",
            turn_index=3,
            speaker=TurnSpeaker.REP,
            stage="close_attempt",
            text="Are you ready to move forward now?",
            normalized_transcript_text="Are you ready to move forward now?",
            transcript_confidence=0.96,
            started_at=started_at + timedelta(seconds=8),
            ended_at=started_at + timedelta(seconds=12),
        ),
        SessionTurn(
            id="ai-2",
            session_id="session-1",
            turn_index=4,
            speaker=TurnSpeaker.AI,
            stage="close_attempt",
            text="Sounds good, let's do it today.",
            emotion_before="skeptical",
            emotion_after="skeptical",
            started_at=started_at + timedelta(seconds=12),
            ended_at=started_at + timedelta(seconds=16),
        ),
    ]
    committed_payloads = [
        {
            "ai_turn_id": turns[1].id,
            "response_plan": {
                "must_answer": True,
                "allowed_new_objection": "price",
                "semantic_anchors": ["budget", "value"],
                "next_step_acceptability": "not_allowed",
            },
            "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
            "transcript_quality": {"confidence": 0.96, "applied_terms": ["Acme Pest Control"]},
            "interrupted": False,
        },
        {
            "ai_turn_id": turns[3].id,
            "response_plan": {
                "must_answer": True,
                "allowed_new_objection": "price",
                "semantic_anchors": ["budget", "value"],
                "next_step_acceptability": "not_allowed",
            },
            "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
            "transcript_quality": {"confidence": 0.96, "applied_terms": ["Acme Pest Control"]},
            "interrupted": False,
        },
    ]

    result = service.evaluate_session(
        turns=turns,
        committed_payloads=committed_payloads,
        quality_signal=ConversationQualitySignal(
            session_id="session-1",
            manager_id="manager-1",
            org_id="org-1",
            realism_rating=2,
            difficulty_appropriate=True,
            signal_responsiveness=2,
            notes="Too soft.",
            flagged_turn_ids=[],
        ),
    )

    assert result.overall_score < 7.0
    assert "over_softening" in result.failure_labels
    assert "repetition" in result.failure_labels
    assert result.repetition_rate > 0


def test_realism_eval_scores_good_homeowner_response_highly():
    service = ConversationRealismEvalService()
    turns, committed_payloads = _make_turn_pair(
        rep_text="We can lower the monthly cost if we get you started today.",
        ai_text=(
            "Before I agree to anything, I need to know the monthly budget and what value we'd actually get. "
            "I'm not ready to schedule anything yet."
        ),
        response_plan={
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["budget", "value"],
            "stance": "guarded",
            "next_step_acceptability": "not_allowed",
        },
        turn_analysis={"direct_response_required": True, "recommended_next_objection": "price"},
    )

    result = service.evaluate_session(turns=turns, committed_payloads=committed_payloads)

    assert result.overall_score >= 7.5
    assert result.objection_carryover_score >= 8.5
    assert result.transcript_entity_score >= 9.5
    assert "missed_objection" not in result.failure_labels
    assert "transcript_corruption" not in result.failure_labels


def test_carryover_score_distinguishes_meaningful_vs_weak_restatements():
    service = ConversationRealismEvalService()

    weak_score, weak_flag = service._carryover_score(
        ai_text="Yeah, price.",
        response_plan={"allowed_new_objection": "price", "semantic_anchors": ["budget", "value"]},
        turn_analysis={},
    )
    strong_score, strong_flag = service._carryover_score(
        ai_text="Price is still the sticking point for me because I need to know the monthly budget before I agree to anything.",
        response_plan={"allowed_new_objection": "price", "semantic_anchors": ["budget", "value"]},
        turn_analysis={},
    )

    assert weak_score < strong_score
    assert weak_flag is True
    assert strong_flag is False


def test_realism_eval_flags_missed_objection_when_homeowner_drops_carryover():
    service = ConversationRealismEvalService()
    turns, committed_payloads = _make_turn_pair(
        rep_text="We can lower the monthly cost if we get you started today.",
        ai_text="Okay.",
        response_plan={
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["budget", "value"],
            "stance": "guarded",
            "next_step_acceptability": "not_allowed",
        },
        turn_analysis={"direct_response_required": True, "recommended_next_objection": "price"},
    )

    result = service.evaluate_session(turns=turns, committed_payloads=committed_payloads)

    assert "missed_objection" in result.failure_labels
    assert result.objection_carryover_score <= 5.0


def test_realism_eval_flags_transcript_corruption_when_confidence_is_low():
    service = ConversationRealismEvalService()
    turns, committed_payloads = _make_turn_pair(
        rep_text="We can inspect the perimeter and deweb the eaves next week.",
        ai_text="Do you mean the outside treatment around the house?",
        response_plan={
            "must_answer": True,
            "allowed_new_objection": "service_detail",
            "semantic_anchors": ["outside treatment", "coverage"],
            "stance": "curious",
            "next_step_acceptability": "info_only",
        },
        turn_analysis={"direct_response_required": True},
        transcript_quality={"confidence": 0.34, "applied_terms": []},
    )

    result = service.evaluate_session(turns=turns, committed_payloads=committed_payloads)

    assert "transcript_corruption" in result.failure_labels
    assert result.transcript_entity_score <= 5.5


def test_emotion_score_uses_prior_homeowner_signals_to_validate_transition():
    service = ConversationRealismEvalService()
    ai_turn = SessionTurn(
        id="ai-signal",
        session_id="session-signal",
        turn_index=2,
        speaker=TurnSpeaker.AI,
        stage="considering",
        text="Okay, tell me more.",
        emotion_before="skeptical",
        emotion_after="curious",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc) + timedelta(seconds=2),
    )

    warmed = service._emotion_score(
        ai_turn=ai_turn,
        ai_text=ai_turn.text,
        response_plan={"stance": "cautiously_open"},
        previous_homeowner_signals=["warming"],
    )
    mismatched = service._emotion_score(
        ai_turn=ai_turn,
        ai_text=ai_turn.text,
        response_plan={"stance": "cautiously_open"},
        previous_homeowner_signals=["hardening"],
    )

    assert warmed > mismatched
