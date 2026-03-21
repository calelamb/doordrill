"""Tests for the PromptBuilder v2 overhaul: emotion-driven guidance, life details, delivery direction."""

from __future__ import annotations

import pytest

from app.services.conversation_orchestrator import (
    HomeownerPersona,
    PersonaEnricher,
    PromptBuilder,
    ScenarioSnapshot,
)


def _make_persona(**overrides) -> HomeownerPersona:
    defaults = dict(
        name="Test Homeowner",
        attitude="guarded",
        concerns=["price"],
        objection_queue=["price"],
        buy_likelihood="medium",
        softening_condition="Be specific and calm.",
        household_type="family with kids",
        home_ownership_years=5,
        pest_history=["saw ants last month"],
        price_sensitivity="medium",
        communication_style="terse",
    )
    defaults.update(overrides)
    return HomeownerPersona(**defaults)


def _make_snapshot(**overrides) -> ScenarioSnapshot:
    defaults = dict(
        name="Test Scenario",
        description="A pest control sales scenario.",
        difficulty=3,
        persona_payload={},
        stages=["door_knock", "initial_pitch", "objection_handling"],
    )
    defaults.update(overrides)
    return ScenarioSnapshot(**defaults)


def _build_prompt(persona=None, stage="LISTENING", emotion="neutral", **kwargs) -> str:
    builder = PromptBuilder()
    p = persona or _make_persona()
    snap = _make_snapshot()
    return builder.build(
        scenario=None,
        persona=p,
        stage=stage,
        scenario_snapshot=snap,
        emotion=emotion,
        **kwargs,
    )


class TestWordCapRemoval:
    """Verify that hard word caps and 'one sentence only' rules are gone."""

    @pytest.mark.parametrize("emotion", ["hostile", "annoyed", "skeptical", "neutral", "curious", "interested"])
    def test_no_maximum_words_in_prompt(self, emotion: str):
        prompt = _build_prompt(emotion=emotion)
        assert "Maximum" not in prompt or "words" not in prompt.split("Maximum")[-1][:20]

    @pytest.mark.parametrize("stage", ["DOOR_OPEN", "LISTENING", "OBJECTING", "CONSIDERING", "CLOSE_WINDOW", "RECOVERY", "ENDED"])
    def test_no_one_sentence_only_in_prompt(self, stage: str):
        prompt = _build_prompt(stage=stage)
        assert "one sentence only" not in prompt.lower()

    def test_response_cap_not_used_in_prompt(self):
        """_response_cap_rule may still exist on the class but should not appear in prompt output."""
        prompt = _build_prompt()
        assert "Maximum 10 words" not in prompt
        assert "Maximum 20 words" not in prompt
        assert "Maximum 30 words" not in prompt

    def test_no_hard_rule_at_end(self):
        prompt = _build_prompt()
        # The old hard_rule started with "RULE:"
        assert "RULE:" not in prompt


class TestEmotionLengthGuidance:
    """Verify emotion-specific length guidance appears in prompts."""

    @pytest.mark.parametrize(
        "emotion,expected_fragment",
        [
            ("hostile", "A few sharp words"),
            ("annoyed", "short and impatient"),
            ("skeptical", "pointed question"),
            ("neutral", "Polite but measured"),
            ("curious", "Ask a real question"),
            ("interested", "warming up"),
        ],
    )
    def test_emotion_guidance_in_prompt(self, emotion: str, expected_fragment: str):
        prompt = _build_prompt(emotion=emotion)
        assert expected_fragment in prompt

    def test_unknown_emotion_falls_back_to_neutral(self):
        prompt = _build_prompt(emotion="confused")
        assert "Polite but measured" in prompt


class TestDeliveryDirection:
    """Verify 'Delivery:' line appears in prompts for each emotion."""

    @pytest.mark.parametrize(
        "emotion,expected_fragment",
        [
            ("hostile", "direct and cutting"),
            ("annoyed", "impatient and clipped"),
            ("skeptical", "guarded and probing"),
            ("neutral", "measured and reserved"),
            ("curious", "open but cautious"),
            ("interested", "warm and engaged"),
        ],
    )
    def test_delivery_direction_in_prompt(self, emotion: str, expected_fragment: str):
        prompt = _build_prompt(emotion=emotion)
        assert "Delivery:" in prompt
        assert expected_fragment in prompt

    def test_unknown_emotion_delivery_falls_back_to_neutral(self):
        prompt = _build_prompt(emotion="confused")
        assert "measured and reserved" in prompt


class TestPersonaLifeDetails:
    """Verify PersonaEnricher adds life detail fields and they appear in prompts."""

    def test_enricher_adds_at_home_reason(self):
        persona = _make_persona(at_home_reason=None)
        enriched = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        assert enriched.at_home_reason is not None
        assert len(enriched.at_home_reason) > 0

    def test_enricher_adds_last_salesperson_experience(self):
        persona = _make_persona(last_salesperson_experience=None)
        enriched = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        assert enriched.last_salesperson_experience is not None

    def test_enricher_adds_specific_memory(self):
        persona = _make_persona(specific_memory=None)
        enriched = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        assert enriched.specific_memory is not None

    def test_enricher_adds_current_mood_reason(self):
        persona = _make_persona(current_mood_reason=None)
        enriched = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        assert enriched.current_mood_reason is not None

    def test_enricher_preserves_existing_life_details(self):
        persona = _make_persona(
            at_home_reason="working from home",
            last_salesperson_experience="had a guy last week",
            specific_memory="neighbor Bob had termites",
            current_mood_reason="relaxing at home",
        )
        enriched = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        assert enriched.at_home_reason == "working from home"
        assert enriched.last_salesperson_experience == "had a guy last week"
        assert enriched.specific_memory == "neighbor Bob had termites"
        assert enriched.current_mood_reason == "relaxing at home"

    def test_life_details_appear_in_prompt(self):
        persona = _make_persona(
            at_home_reason="working from home today",
            last_salesperson_experience="had a solar guy come by last week",
            specific_memory="neighbor Bob had termites last year",
            current_mood_reason="was reading in the living room",
        )
        prompt = _build_prompt(persona=persona)
        assert "You are home because: working from home today" in prompt
        assert "Recent salesperson experience: had a solar guy come by last week" in prompt
        assert "Something on your mind: neighbor Bob had termites last year" in prompt
        assert "You were just: was reading in the living room" in prompt

    def test_life_details_not_in_prompt_when_none(self):
        persona = _make_persona(
            at_home_reason=None,
            last_salesperson_experience=None,
            specific_memory=None,
            current_mood_reason=None,
        )
        prompt = _build_prompt(persona=persona)
        assert "You are home because:" not in prompt
        assert "Recent salesperson experience:" not in prompt
        assert "Something on your mind:" not in prompt
        assert "You were just:" not in prompt

    def test_enricher_deterministic(self):
        persona = _make_persona(
            at_home_reason=None,
            last_salesperson_experience=None,
            specific_memory=None,
            current_mood_reason=None,
        )
        enriched1 = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        enriched2 = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        assert enriched1.at_home_reason == enriched2.at_home_reason
        assert enriched1.last_salesperson_experience == enriched2.last_salesperson_experience
        assert enriched1.specific_memory == enriched2.specific_memory
        assert enriched1.current_mood_reason == enriched2.current_mood_reason

    def test_pest_history_stays_list(self):
        persona = _make_persona(pest_history=[])
        enriched = PersonaEnricher.enrich(persona, 3, "pest control scenario")
        assert isinstance(enriched.pest_history, list)

    def test_from_payload_reads_life_details(self):
        payload = {
            "name": "Jane",
            "attitude": "friendly",
            "concerns": [],
            "objection_queue": [],
            "buy_likelihood": "high",
            "softening_condition": "Be nice",
            "at_home_reason": "day off work",
            "last_salesperson_experience": "had lawn care guy",
            "specific_memory": "saw spiders in garage",
            "current_mood_reason": "just finished lunch",
        }
        persona = HomeownerPersona.from_payload(payload)
        assert persona.at_home_reason == "day off work"
        assert persona.last_salesperson_experience == "had lawn care guy"
        assert persona.specific_memory == "saw spiders in garage"
        assert persona.current_mood_reason == "just finished lunch"


class TestTokenBudgetRemoval:
    """Verify PromptBuilder.build doesn't reference homeowner_token_budget."""

    def test_no_token_budget_in_prompt(self):
        prompt = _build_prompt()
        assert "homeowner_token_budget" not in prompt
        assert "token_budget" not in prompt

    def test_no_token_budget_param(self):
        import inspect
        sig = inspect.signature(PromptBuilder.build)
        assert "homeowner_token_budget" not in sig.parameters
