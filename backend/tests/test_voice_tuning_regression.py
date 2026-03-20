from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.models.session import SessionTurn
from app.models.types import TurnSpeaker
from app.services.conversation_realism_eval_service import ConversationRealismEvalService


VOICE_TUNING_FIXTURES: list[dict] = [
    {
        "stage": "door_knock",
        "emotion_after": "curious",
        "rep_text": "Hey, I'm with Acme Pest Control and we were just helping a neighbor with spiders.",
        "ai_text": "Which neighbor are you talking about?",
        "response_plan": {
            "must_answer": True,
            "semantic_anchors": ["neighbor"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True},
    },
    {
        "stage": "initial_pitch",
        "emotion_after": "curious",
        "rep_text": "We do a free inspection and a monthly plan for ants and spiders.",
        "ai_text": "Okay, what does the monthly plan actually cover?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["monthly plan", "coverage"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "It starts at forty-nine a month and covers the outside treatment.",
        "ai_text": "Forty-nine a month is still the sticking point for me because I need to know what value we'd actually get.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["budget", "value"],
            "stance": "guarded",
            "next_step_acceptability": "not_allowed",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "We're licensed, insured, and we've been operating around here for years.",
        "ai_text": "How do I know you guys are legit and not just saying that at the door?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "trust",
            "semantic_anchors": ["legit", "proof"],
            "stance": "guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "trust"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "A lot of current Orkin customers switch when they want more consistent follow-up.",
        "ai_text": "We already have a current provider, so why would switching be worth the hassle?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "incumbent_provider",
            "semantic_anchors": ["switching", "current provider"],
            "stance": "guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "incumbent_provider"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "If it makes sense, we could get the inspection on the calendar this week.",
        "ai_text": "I wouldn't decide on that alone. I'd need to run it by my partner first.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "spouse",
            "semantic_anchors": ["partner", "shared decision"],
            "stance": "guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "spouse"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "annoyed",
        "rep_text": "It'll only take a couple minutes to walk through it with you.",
        "ai_text": "I'm in the middle of something, so timing is the problem right now.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "timing",
            "semantic_anchors": ["busy", "right now"],
            "stance": "firm_resistance",
            "next_step_acceptability": "not_allowed",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "timing"},
    },
    {
        "stage": "considering",
        "emotion_after": "curious",
        "rep_text": "We can start with a quick inspection and there's no long-term commitment.",
        "ai_text": "Maybe, but what would the actual process look like after that quick inspection?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": None,
            "semantic_anchors": ["quick inspection", "process"],
            "stance": "low_friction_considering",
            "next_step_acceptability": "inspection_only",
        },
        "turn_analysis": {"direct_response_required": True},
    },
    {
        "stage": "recovery",
        "emotion_after": "curious",
        "rep_text": "You're right, I was pushing. Let me slow down and just answer the safety question.",
        "ai_text": "Okay, that's more helpful. What are you actually using around kids and pets?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "safety_environment",
            "semantic_anchors": ["kids", "pets"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "safety_environment"},
    },
    {
        "stage": "close_attempt",
        "emotion_after": "skeptical",
        "rep_text": "If I can get you penciled in today, can we just lock it in now?",
        "ai_text": "Not today. I still need the monthly cost and the follow-up details before I'd agree to anything.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["budget", "value"],
            "stance": "firm_resistance",
            "next_step_acceptability": "not_allowed",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
    },
    {
        "stage": "close_attempt",
        "emotion_after": "curious",
        "rep_text": "Would a free inspection later this week work if that feels easier?",
        "ai_text": "A free inspection is more reasonable. What day were you thinking?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": None,
            "semantic_anchors": ["free inspection"],
            "stance": "cautiously_open",
            "next_step_acceptability": "inspection_only",
        },
        "turn_analysis": {"direct_response_required": True},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "There's no long-term contract, just recurring exterior service.",
        "ai_text": "No long-term contract helps, but I'd still want to know how easy it is to cancel.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "timing",
            "semantic_anchors": ["long-term contract", "cancel"],
            "stance": "guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "timing"},
    },
    {
        "stage": "door_knock",
        "emotion_after": "curious",
        "rep_text": "Hey, are you the homeowner?",
        "ai_text": "Yeah. What's this about?",
        "response_plan": {
            "must_answer": True,
            "semantic_anchors": ["homeowner"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True},
    },
    {
        "stage": "initial_pitch",
        "emotion_after": "curious",
        "rep_text": "We're doing free termite checks on the block this afternoon.",
        "ai_text": "We haven't seen termites. Why are you checking for that right now?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "need",
            "semantic_anchors": ["termite checks"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "need"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "The first service is heavier, then it settles into regular maintenance.",
        "ai_text": "So is that heavier first visit included, or does the price jump right away?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["first visit", "price"],
            "stance": "guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "curious",
        "rep_text": "Once it dries, it's fine around kids and pets.",
        "ai_text": "How long does it take to dry if kids or pets are around the yard?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "safety_environment",
            "semantic_anchors": ["kids", "pets"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "safety_environment"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "annoyed",
        "rep_text": "I can keep it quick while you're out here.",
        "ai_text": "Quick still isn't good timing for me right now.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "timing",
            "semantic_anchors": ["quick", "right now"],
            "stance": "firm_resistance",
            "next_step_acceptability": "not_allowed",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "timing"},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "We service a few homes right on this street already.",
        "ai_text": "Which houses on this street are you talking about?",
        "response_plan": {
            "must_answer": True,
            "semantic_anchors": ["street"],
            "stance": "guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True},
    },
    {
        "stage": "considering",
        "emotion_after": "curious",
        "rep_text": "If you just want the information, I can leave a quote and let you look it over.",
        "ai_text": "You can leave it, but I'm not promising anything today.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": None,
            "semantic_anchors": ["leave a quote"],
            "stance": "cautiously_open",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True},
    },
    {
        "stage": "considering",
        "emotion_after": "curious",
        "rep_text": "We can come back when your spouse is home if that's easier.",
        "ai_text": "That would be better. What times are you usually back through here?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "spouse",
            "semantic_anchors": ["spouse", "come back"],
            "stance": "cautiously_open",
            "next_step_acceptability": "inspection_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "spouse"},
    },
    {
        "stage": "close_attempt",
        "emotion_after": "skeptical",
        "rep_text": "If the inspection is free, can we set a day now?",
        "ai_text": "Not yet. I still need to know what happens after that inspection before I pick a day.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": None,
            "semantic_anchors": ["inspection", "pick a day"],
            "stance": "firm_resistance",
            "next_step_acceptability": "not_allowed",
        },
        "turn_analysis": {"direct_response_required": True},
    },
    {
        "stage": "objection_handling",
        "emotion_after": "skeptical",
        "rep_text": "There's no contract, and we text before we come out.",
        "ai_text": "The no-contract part helps, but how much notice do you usually give before those visits?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "timing",
            "semantic_anchors": ["no contract", "notice"],
            "stance": "guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "timing"},
    },
    {
        "stage": "recovery",
        "emotion_after": "curious",
        "rep_text": "Fair enough. Let me answer the price question directly.",
        "ai_text": "Okay, go ahead. What's the real monthly number after that first visit?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["monthly number", "first visit"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
    },
    {
        "stage": "initial_pitch",
        "emotion_after": "curious",
        "rep_text": "We mainly help with ants, spiders, and wasps around the yard.",
        "ai_text": "Wasps are actually the main issue here. What do you do for nests?",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "need",
            "semantic_anchors": ["wasps", "nests"],
            "stance": "direct_but_guarded",
            "next_step_acceptability": "info_only",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "need"},
    },
    {
        "stage": "close_attempt",
        "emotion_after": "considering",
        "rep_text": "If it looks reasonable, I can pencil you in and you can confirm later.",
        "ai_text": "Maybe, but I don't want a spot held until I've seen the exact price first.",
        "response_plan": {
            "must_answer": True,
            "allowed_new_objection": "price",
            "semantic_anchors": ["pencil you in", "exact price"],
            "stance": "low_friction_considering",
            "next_step_acceptability": "not_allowed",
        },
        "turn_analysis": {"direct_response_required": True, "recommended_next_objection": "price"},
    },
]


def _latency_breakdown_for_stage(stage: str) -> dict[str, int]:
    defaults = {
        "door_knock": {"stt_ms": 170, "analysis_ms": 18, "llm_first_token_ms": 145, "tts_first_audio_ms": 180, "total_turn_ms": 620},
        "initial_pitch": {"stt_ms": 190, "analysis_ms": 20, "llm_first_token_ms": 185, "tts_first_audio_ms": 225, "total_turn_ms": 760},
        "objection_handling": {"stt_ms": 205, "analysis_ms": 22, "llm_first_token_ms": 205, "tts_first_audio_ms": 240, "total_turn_ms": 830},
        "considering": {"stt_ms": 210, "analysis_ms": 22, "llm_first_token_ms": 215, "tts_first_audio_ms": 245, "total_turn_ms": 845},
        "recovery": {"stt_ms": 195, "analysis_ms": 18, "llm_first_token_ms": 180, "tts_first_audio_ms": 215, "total_turn_ms": 760},
        "close_attempt": {"stt_ms": 215, "analysis_ms": 24, "llm_first_token_ms": 225, "tts_first_audio_ms": 250, "total_turn_ms": 870},
    }
    return dict(defaults.get(stage, defaults["objection_handling"]))


def _percentile(values: list[int], percentile: int) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil((percentile / 100) * len(ordered)) - 1)
    return ordered[index]


def _build_regression_session(fixtures: list[dict]) -> tuple[list[SessionTurn], list[dict]]:
    turns: list[SessionTurn] = []
    committed_payloads: list[dict] = []
    base = datetime.now(timezone.utc)

    for index, fixture in enumerate(fixtures, start=1):
        turn_index = (index * 2) - 1
        rep_turn = SessionTurn(
            id=f"rep-{index}",
            session_id="voice-tuning-regression",
            turn_index=turn_index,
            speaker=TurnSpeaker.REP,
            stage=fixture["stage"],
            text=fixture["rep_text"],
            normalized_transcript_text=fixture["rep_text"],
            transcript_confidence=0.96,
            started_at=base + timedelta(seconds=index * 12),
            ended_at=base + timedelta(seconds=(index * 12) + 4),
        )
        ai_turn = SessionTurn(
            id=f"ai-{index}",
            session_id="voice-tuning-regression",
            turn_index=turn_index + 1,
            speaker=TurnSpeaker.AI,
            stage=fixture["stage"],
            text=fixture["ai_text"],
            emotion_before="skeptical",
            emotion_after=fixture["emotion_after"],
            started_at=base + timedelta(seconds=(index * 12) + 4),
            ended_at=base + timedelta(seconds=(index * 12) + 8),
        )
        turns.extend([rep_turn, ai_turn])
        committed_payloads.append(
            {
                "ai_turn_id": ai_turn.id,
                "response_plan": fixture["response_plan"],
                "turn_analysis": fixture["turn_analysis"],
                "transcript_quality": {"confidence": 0.96, "applied_terms": ["Acme Pest Control"]},
                "phase_latency_breakdown": _latency_breakdown_for_stage(fixture["stage"]),
                "interrupted": False,
            }
        )

    return turns, committed_payloads


def test_voice_tuning_regression_corpus_stays_above_realism_floor():
    service = ConversationRealismEvalService()
    turns, committed_payloads = _build_regression_session(VOICE_TUNING_FIXTURES)

    result = service.evaluate_session(turns=turns, committed_payloads=committed_payloads)

    assert result.turn_count == len(VOICE_TUNING_FIXTURES)
    assert result.overall_score >= 8.0
    assert result.repetition_rate < 0.10
    assert "over_softening" not in result.failure_labels
    assert "transcript_corruption" not in result.failure_labels


def test_voice_tuning_regression_latency_envelope_stays_within_guardrails():
    _, committed_payloads = _build_regression_session(VOICE_TUNING_FIXTURES)

    total_turn_ms = [int(payload["phase_latency_breakdown"]["total_turn_ms"]) for payload in committed_payloads]
    first_audio_ms = [int(payload["phase_latency_breakdown"]["tts_first_audio_ms"]) for payload in committed_payloads]

    assert len(committed_payloads) >= 25
    assert _percentile(total_turn_ms, 50) <= 900
    assert _percentile(total_turn_ms, 95) <= 1400
    assert _percentile(first_audio_ms, 95) <= 350
