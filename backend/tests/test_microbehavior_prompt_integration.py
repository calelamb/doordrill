from __future__ import annotations

import pytest

from app.services.conversation_orchestrator import (
    BehaviorDirectives,
    ConversationOrchestrator,
    HomeownerPersona,
    PromptBuilder,
)
from app.services.micro_behavior_engine import MicroBehaviorPlan
from app.services.micro_behavior_engine import (
    FILLER_VARIANTS,
    HESITATION_VARIANTS,
    INTERRUPTION_VARIANTS,
    ConversationalMicroBehaviorEngine,
)


def _persona() -> HomeownerPersona:
    return HomeownerPersona.from_payload(
        {
            "name": "Pat Homeowner",
            "attitude": "skeptical",
            "concerns": ["price", "trust"],
            "objection_queue": ["I need to think about it"],
            "buy_likelihood": "medium",
            "softening_condition": "The rep has to be specific and low pressure.",
        }
    )


@pytest.mark.parametrize(
    ("emotion_after", "expected_tone", "expected_length"),
    [
        ("neutral", "measured", "medium"),
        ("skeptical", "guarded", "medium"),
        ("annoyed", "sharp", "short"),
        ("hostile", "confrontational", "short"),
        ("curious", "exploratory", "long"),
        ("interested", "warm", "long"),
    ],
)
def test_compute_behavior_directives_matches_emotion_defaults(
    emotion_after: str,
    expected_tone: str,
    expected_length: str,
):
    orchestrator = ConversationOrchestrator()

    directives = orchestrator.compute_behavior_directives(
        emotion_before=emotion_after,
        emotion_after=emotion_after,
        behavioral_signals=[],
        active_objections=[],
    )

    assert directives.tone == expected_tone
    assert directives.sentence_length == expected_length


def test_compute_behavior_directives_uses_signal_overrides():
    orchestrator = ConversationOrchestrator()

    warming = orchestrator.compute_behavior_directives(
        emotion_before="neutral",
        emotion_after="curious",
        behavioral_signals=["acknowledges_concern"],
        active_objections=["trust"],
    )
    cutting = orchestrator.compute_behavior_directives(
        emotion_before="skeptical",
        emotion_after="hostile",
        behavioral_signals=["ignores_objection", "pushes_close"],
        active_objections=["price"],
    )

    assert warming.tone == "warming"
    assert warming.sentence_length == "long"
    assert cutting.tone == "cutting"
    assert cutting.sentence_length == "short"


def test_compute_behavior_directives_uses_communication_style_constraints():
    orchestrator = ConversationOrchestrator()

    terse = orchestrator.compute_behavior_directives(
        emotion_before="neutral",
        emotion_after="neutral",
        behavioral_signals=[],
        active_objections=[],
        communication_style="terse",
    )
    chatty = orchestrator.compute_behavior_directives(
        emotion_before="neutral",
        emotion_after="neutral",
        behavioral_signals=[],
        active_objections=[],
        communication_style="chatty",
    )

    assert terse.sentence_length == "short"
    assert "Communication style: terse." in terse.directive_text
    assert chatty.sentence_length == "long"
    assert "Communication style: chatty." in chatty.directive_text


def test_compute_behavior_directives_sets_interruption_mode_for_hostile_pushback():
    orchestrator = ConversationOrchestrator()

    directives = orchestrator.compute_behavior_directives(
        emotion_before="skeptical",
        emotion_after="hostile",
        behavioral_signals=["ignores_objection"],
        active_objections=["trust"],
    )

    assert directives.interruption_mode is True
    assert "Interrupt the rep:" in directives.directive_text


def test_micro_behavior_variant_pools_are_deep_enough():
    assert all(len(options) >= 6 for options in HESITATION_VARIANTS.values())
    assert all(len(options) >= 5 for options in FILLER_VARIANTS.values())
    assert len(INTERRUPTION_VARIANTS["annoyed"]) >= 7
    assert len(INTERRUPTION_VARIANTS["hostile"]) >= 7


def test_compute_behavior_directives_leaves_interruption_mode_off_for_neutral_signals():
    orchestrator = ConversationOrchestrator()

    directives = orchestrator.compute_behavior_directives(
        emotion_before="neutral",
        emotion_after="annoyed",
        behavioral_signals=["explains_value"],
        active_objections=["price"],
    )

    assert directives.interruption_mode is False
    assert "Interrupt the rep:" not in directives.directive_text


def test_prompt_builder_includes_behavior_directives_block():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v1",
        behavior_directives=BehaviorDirectives(
            tone="guarded",
            sentence_length="medium",
            interruption_mode=False,
            directive_text=(
                "LAYER 3C - BEHAVIORAL DIRECTIVES\n"
                "Tone for this response: guarded. Write in this register throughout.\n"
                "Response length: medium. Two sentences max.\n"
                "Do not exceed these constraints. The delivery will match exactly what you write."
            ),
        ),
    )

    assert "LAYER 3C - BEHAVIORAL DIRECTIVES" in prompt
    assert "Respond in no more than two sentences." in prompt
    assert "RULE: Respond in one sentence only." not in prompt


def test_prompt_builder_includes_prior_turn_register_block():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v1",
        last_mb_context={
            "tone": "guarded",
            "sentence_length": "medium",
            "interruption_type": "homeowner_cuts_off_rep",
        },
    )

    assert "LAYER 3B-CONT - PRIOR TURN REGISTER" in prompt
    assert "tone was guarded, length was medium, you interrupted." in prompt


def test_prompt_builder_omits_new_blocks_when_behavior_context_is_missing():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v1",
    )

    assert "LAYER 3B-CONT - PRIOR TURN REGISTER" not in prompt
    assert "LAYER 3C - BEHAVIORAL DIRECTIVES" not in prompt


def test_prompt_builder_includes_persona_communication_style_guardrail():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=HomeownerPersona.from_payload(
            {
                "name": "Pat Homeowner",
                "attitude": "skeptical",
                "concerns": ["price"],
                "communication_style": "analytical",
            }
        ),
        stage="objection_handling",
        prompt_version="conversation_v1",
    )

    assert "Permanent persona communication style constraint (analytical):" in prompt
    assert "specific, probing follow-ups" in prompt


def test_update_last_mb_plan_updates_session_context():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-mb",
        scenario_name="Guarded Homeowner",
        scenario_description="A skeptical homeowner is not easy to win over.",
        difficulty=3,
        persona={"attitude": "skeptical", "concerns": ["price"]},
    )

    plan = MicroBehaviorPlan(
        transformed_text="Wait, no thanks.",
        tone="cutting",
        sentence_length="short",
        interruption_type="homeowner_cuts_off_rep",
        behaviors=["tone_shift", "homeowner_cuts_off_rep"],
        pause_profile={"opening_pause_ms": 80, "total_pause_ms": 260, "longest_pause_ms": 180},
        realism_score=7.4,
        segments=[],
    )

    orchestrator.update_last_mb_plan("session-mb", plan)

    assert orchestrator._contexts["session-mb"].last_mb_plan == {
        "tone": "cutting",
        "sentence_length": "short",
        "interruption_type": "homeowner_cuts_off_rep",
        "behaviors": ["tone_shift", "homeowner_cuts_off_rep"],
        "realism_score": 7.4,
    }


def test_prepare_rep_turn_injects_prior_register_and_behavior_directives():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-prompt",
        scenario_name="Guarded Homeowner",
        scenario_description="A skeptical homeowner wants proof before considering the offer.",
        difficulty=3,
        persona={"attitude": "skeptical", "concerns": ["price", "trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering"],
    )
    orchestrator._contexts["session-prompt"].last_mb_plan = {
        "tone": "guarded",
        "sentence_length": "medium",
        "interruption_type": None,
        "behaviors": ["tone_shift"],
        "realism_score": 6.5,
    }

    plan = orchestrator.prepare_rep_turn(
        "session-prompt",
        "I understand price matters and I can show proof from local reviews.",
    )

    assert "LAYER 3B-CONT - PRIOR TURN REGISTER" in plan.system_prompt
    assert "LAYER 3C - BEHAVIORAL DIRECTIVES" in plan.system_prompt
    assert plan.behavior_directives.tone
    assert plan.behavior_directives.sentence_length


def test_microbehavior_shortening_preserves_active_objection_semantics():
    engine = ConversationalMicroBehaviorEngine()

    plan = engine.apply_to_response(
        session_id="session-semantic-safe",
        raw_text="I get what you're saying. My bigger issue is still the price right now.",
        emotion_before="skeptical",
        emotion_after="annoyed",
        behavioral_signals=["pushes_close"],
        active_objections=["price"],
    )

    assert "price" in plan.transformed_text.lower()
