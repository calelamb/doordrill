from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.session import SessionTurn
from app.models.training import ConversationQualitySignal
from app.models.types import TurnSpeaker
from app.services.conversation_realism_eval_service import ConversationRealismEvalService


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
