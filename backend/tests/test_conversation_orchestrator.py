import pytest
from app.services.conversation_orchestrator import (
    ConversationOrchestrator,
    ConversationTurnAnalyzer,
    ConversationState,
    TurnAnalysis,
    SOCIAL_PROOF_PHRASES,
    RAPPORT_PHRASES,
)


def test_starting_state_comes_from_persona_scenario_and_seeded_objections():
    orchestrator = ConversationOrchestrator()

    state = orchestrator.initialize_session(
        "session-a",
        scenario_name="Skeptical Homeowner",
        scenario_description="Rep handles a skeptical homeowner with pricing concerns.",
        difficulty=2,
        persona={"attitude": "skeptical", "concerns": ["price", "trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    assert state.stage == "door_knock"
    assert state.emotion == "skeptical"
    assert state.active_objections == ["price", "trust"]
    assert state.queued_objections == []
    assert state.objection_pressure == 3


def test_friendly_low_difficulty_persona_starts_interested_without_active_objections():
    orchestrator = ConversationOrchestrator()

    state = orchestrator.initialize_session(
        "session-open",
        scenario_name="Friendly First Door",
        scenario_description="A friendly retired teacher answers the door and is open to hearing a short pitch.",
        difficulty=1,
        persona={
            "attitude": "friendly but practical",
            "concerns": ["trust"],
            "buy_likelihood": "high",
        },
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    assert state.emotion == "interested"
    assert state.active_objections == []
    assert state.queued_objections == ["trust"]
    assert state.objection_pressure == 0


def test_acknowledgement_and_value_reduce_pressure_and_resolve_objection():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-b",
        scenario_name="Skeptical Homeowner",
        scenario_description="Rep handles monthly service concerns.",
        difficulty=2,
        persona={"attitude": "skeptical", "concerns": ["price", "trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn(
        "session-b",
        "Hi, I understand price matters and I appreciate your time. We can save you money and protect the home.",
    )

    assert plan.stage_after == "objection_handling"
    assert plan.emotion_before == "skeptical"
    assert plan.emotion_after == "curious"
    assert "acknowledges_concern" in plan.behavioral_signals
    assert "explains_value" in plan.behavioral_signals
    assert plan.resolved_objections == ["price"]
    assert plan.objection_pressure_after < plan.objection_pressure_before
    assert "price" not in plan.active_objections
    assert plan.reaction_intent.startswith("This is turn 1.")
    assert plan.turn_analysis.objection_status == "partial"
    assert plan.response_plan.allowed_new_objection is None
    assert plan.response_plan.friction_level == 1


def test_ignoring_objections_escalates_to_hostile_and_surfaces_next_concern():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-c",
        scenario_name="Stacked Objections",
        scenario_description="A skeptical homeowner is guarded, cost-focused, and already uses another provider.",
        difficulty=4,
        persona={
            "attitude": "skeptical",
            "concerns": ["price", "spouse", "incumbent_provider"],
        },
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn("session-c", "Sign today right now. Let's close this.")

    assert plan.stage_after == "close_attempt"
    assert plan.emotion_after == "hostile"
    assert "pushes_close" in plan.behavioral_signals
    assert "ignores_objection" not in plan.behavioral_signals
    assert plan.active_objections == ["price", "spouse"]
    assert plan.queued_objections == ["incumbent_provider"]
    assert plan.objection_pressure_after == 5
    assert plan.turn_analysis.recommended_next_objection == "price"
    assert plan.response_plan.next_step_acceptability == "not_allowed"
    assert plan.response_plan.stance == "firm_resistance"


def test_system_prompt_includes_pressure_resolved_and_latent_objections():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-d",
        scenario_name="Stacked Concerns",
        scenario_description="A skeptical homeowner wants proof before considering the service.",
        difficulty=2,
        persona={"attitude": "skeptical", "concerns": ["price", "trust", "spouse"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn(
        "session-d",
        "Hello, I understand price matters and appreciate your time. We can save you money with a local team.",
    )

    assert "Current emotional state:" in plan.system_prompt
    assert "Objection pressure:" in plan.system_prompt
    assert "Latent objections still available to surface: spouse." in plan.system_prompt
    assert "Recently resolved objections: price." in plan.system_prompt
    assert "LAYER 3A-PLAN - RESPONSE PLAN" in plan.system_prompt


def test_direct_question_uses_fast_path_and_requires_answer_first():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-e",
        scenario_name="Measured Homeowner",
        scenario_description="A practical homeowner asks short follow-up questions before engaging.",
        difficulty=2,
        persona={"attitude": "neutral", "concerns": ["trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn(
        "session-e",
        "What would make you feel comfortable hearing a quick overview?",
    )

    assert plan.response_plan.must_answer is True
    assert plan.response_plan.fast_path_prompt is True
    assert "Fast path: answer directly" in plan.system_prompt


def test_realism_pack_and_wording_rotation_show_up_in_prompt():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-f",
        scenario_name="Couple Decision",
        scenario_description="A skeptical homeowner says their spouse is involved in decisions.",
        difficulty=4,
        persona={"attitude": "skeptical", "concerns": ["spouse", "trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    first_plan = orchestrator.prepare_rep_turn("session-f", "Can we get this scheduled today?")
    second_plan = orchestrator.prepare_rep_turn("session-f", "If not today, what would hold you back?")

    assert "LAYER 2B - STABLE REALISM TRAITS" in first_plan.system_prompt
    assert first_plan.response_plan.wording_rotation_hint is None
    assert second_plan.response_plan.wording_rotation_hint is not None


def test_first_turn_contract_blocks_new_objections_and_caps_friction():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-first-turn",
        scenario_name="Guarded First Door",
        scenario_description="A skeptical homeowner answers the door.",
        difficulty=4,
        persona={"attitude": "skeptical", "concerns": ["price", "trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn("session-first-turn", "Hey, how's it going?")

    assert plan.response_plan.allowed_new_objection is None
    assert plan.response_plan.friction_level == 1
    assert plan.reaction_intent.startswith("This is turn 1.")
    assert "price" not in " ".join(plan.response_plan.semantic_anchors).lower()
    assert "trust" not in " ".join(plan.response_plan.semantic_anchors).lower()


def test_first_turn_neighbor_mention_stays_on_the_specific_claim():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-first-neighbor",
        scenario_name="Neighbor Mention",
        scenario_description="A homeowner answers the door.",
        difficulty=3,
        persona={"attitude": "neutral", "concerns": ["price"]},
        stages=["door_knock", "initial_pitch", "objection_handling"],
    )

    plan = orchestrator.prepare_rep_turn(
        "session-first-neighbor",
        "Hey, we were helping your neighbor a few houses down and wanted to introduce ourselves.",
    )

    assert "neighbor" in plan.reaction_intent.lower()
    assert plan.response_plan.allowed_new_objection is None


def test_ignored_objection_escalation_progresses_through_three_stages():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-ignored-stages",
        scenario_name="Repeated Dodge",
        scenario_description="A guarded homeowner wants a price answer before listening further.",
        difficulty=3,
        persona={"attitude": "guarded", "concerns": ["price"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering"],
    )
    state = orchestrator.get_state("session-ignored-stages")
    state.stage = "objection_handling"
    state.rep_turns = 1

    first = orchestrator.prepare_rep_turn("session-ignored-stages", "Let me tell you more about our program first.")
    second = orchestrator.prepare_rep_turn("session-ignored-stages", "Before that, I just want to show you the service.")
    third = orchestrator.prepare_rep_turn("session-ignored-stages", "Just hear me out for another second.")

    assert "last concern about price" in first.reaction_intent
    assert first.behavior_directives.interruption_mode is False
    assert "ignored your concern about price twice" in second.reaction_intent
    assert third.behavior_directives.interruption_mode is True
    assert "ending the conversation" in third.reaction_intent
    assert "ignored_objection_wall" in third.active_edge_cases


def test_emotion_momentum_requires_multiple_good_turns_to_recover():
    orchestrator = ConversationOrchestrator()
    analysis = TurnAnalysis(
        stage_intent="handle_objection",
        referenced_concerns=["price"],
        addressed_objections=["price"],
        resolved_objections=["price"],
        partially_addressed_objections=[],
        objection_status="resolved",
        objection_status_map={"price": "resolved"},
        behavioral_signals=["acknowledges_concern", "reduces_pressure"],
        rapport_delta=0,
        pressure_delta=-1,
        recommended_next_objection=None,
        reaction_intent="Answer directly.",
        homeowner_posture="defensive",
        homeowner_signals=[],
        direct_response_required=False,
        confidence=0.8,
        resolution_progress={"price": 3},
    )

    emotion, momentum = orchestrator._transition_emotion_from_analysis(
        current_emotion="annoyed",
        current_momentum=-3,
        pressure_before=3,
        pressure_after=2,
        analysis=analysis,
    )
    second_emotion, second_momentum = orchestrator._transition_emotion_from_analysis(
        current_emotion=emotion,
        current_momentum=momentum,
        pressure_before=2,
        pressure_after=1,
        analysis=analysis,
    )
    third_emotion, _ = orchestrator._transition_emotion_from_analysis(
        current_emotion=second_emotion,
        current_momentum=second_momentum,
        pressure_before=1,
        pressure_after=0,
        analysis=analysis,
    )

    assert emotion == "annoyed"
    assert second_emotion == "skeptical"
    assert third_emotion == "neutral"


def test_anchor_validation_and_posture_clamp_prevent_conflicting_plan():
    orchestrator = ConversationOrchestrator()

    assert orchestrator._validate_anchors(["curious about pricing", "budget and value"], "firm_resistance") == ["budget and value"]
    assert orchestrator._resolve_posture_friction_conflict(posture="warming_up", friction_level=4) == 2
    assert orchestrator._resolve_posture_friction_conflict(posture="pushing_back", friction_level=1) == 3


def test_friction_memory_penalizes_stalls_without_growing_unbounded():
    orchestrator = ConversationOrchestrator()

    baseline = orchestrator._friction_level_for_turn(
        next_step_acceptability="info_only",
        active_objections=["price"],
        objection_pressure=1,
        emotion="neutral",
        turns_since_positive_signal=0,
    )
    stalled = orchestrator._friction_level_for_turn(
        next_step_acceptability="info_only",
        active_objections=["price"],
        objection_pressure=1,
        emotion="neutral",
        turns_since_positive_signal=4,
    )
    deeply_stalled = orchestrator._friction_level_for_turn(
        next_step_acceptability="info_only",
        active_objections=["price"],
        objection_pressure=1,
        emotion="neutral",
        turns_since_positive_signal=12,
    )

    assert stalled >= baseline + 2
    assert deeply_stalled == stalled


def test_fatigue_directive_appears_and_shifts_for_high_rapport():
    orchestrator = ConversationOrchestrator()

    assert orchestrator._fatigue_modifier(rep_turns=10, rapport_score=0) is not None
    assert "wrap it up" in orchestrator._fatigue_modifier(rep_turns=15, rapport_score=0).lower()
    assert "wrap it up" not in orchestrator._fatigue_modifier(rep_turns=17, rapport_score=5).lower()
    assert "wrap it up" in orchestrator._fatigue_modifier(rep_turns=18, rapport_score=5).lower()


def test_objection_fatigue_turns_into_dealbreaker_after_third_raise():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-objection-fatigue",
        scenario_name="Dealbreaker Price",
        scenario_description="An annoyed homeowner keeps bringing price back up.",
        difficulty=3,
        persona={"attitude": "annoyed", "concerns": ["price"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering"],
    )
    state = orchestrator.get_state("session-objection-fatigue")
    state.stage = "objection_handling"
    state.rep_turns = 2
    state.emotion = "annoyed"
    state.active_objections = ["price"]
    state.objection_raise_count["price"] = 2

    plan = orchestrator.prepare_rep_turn("session-objection-fatigue", "Let me explain the service before we get into that.")

    assert "dealbreaker" in plan.reaction_intent.lower()


def test_weighted_booking_gate_uses_score_and_low_buy_likelihood_requires_more():
    orchestrator = ConversationOrchestrator()
    state = orchestrator.initialize_session(
        "session-booking-score",
        scenario_name="Open Homeowner",
        scenario_description="A homeowner is hearing the rep out.",
        difficulty=2,
        persona={"attitude": "neutral", "buy_likelihood": "medium-high"},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )
    context = orchestrator.get_context("session-booking-score")
    assert context is not None

    state.rapport_score = 3
    state.resolved_objections = ["price", "trust"]
    state.objection_pressure = 1
    state.emotion = "neutral"
    state.active_objections = []

    booking_score = orchestrator._compute_booking_score(state=state, persona=context.persona)
    acceptability = orchestrator._next_step_acceptability_from_score(
        stage_after="close_attempt",
        booking_score=booking_score,
        persona=context.persona,
        active_objections=list(state.active_objections),
    )

    low_persona = context.persona.from_payload(
        {
            "name": context.persona.name,
            "attitude": context.persona.attitude,
            "concerns": context.persona.concerns,
            "buy_likelihood": "low",
        }
    )
    low_acceptability = orchestrator._next_step_acceptability_from_score(
        stage_after="close_attempt",
        booking_score=booking_score,
        persona=low_persona,
        active_objections=list(state.active_objections),
    )
    with_active_objection = orchestrator._next_step_acceptability_from_score(
        stage_after="close_attempt",
        booking_score=booking_score,
        persona=context.persona,
        active_objections=["price"],
    )

    assert booking_score >= 6
    assert acceptability == "booking_possible"
    assert low_acceptability == "inspection_only"
    assert with_active_objection == "info_only"


def test_pending_test_question_re_surfaces_when_rep_dodges_it():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-pending-test",
        scenario_name="Insurance Proof",
        scenario_description="A skeptical homeowner wants proof.",
        difficulty=3,
        persona={"attitude": "skeptical", "concerns": ["trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering"],
    )
    state = orchestrator.get_state("session-pending-test")
    state.stage = "objection_handling"
    state.rep_turns = 1
    orchestrator.record_turn(
        "session-pending-test",
        speaker="homeowner",
        text="How do I know you're insured?",
        stage="objection_handling",
        emotion="skeptical",
    )

    dodge = orchestrator.prepare_rep_turn("session-pending-test", "We help a lot of homes in the neighborhood.")
    answer = orchestrator.prepare_rep_turn(
        "session-pending-test",
        "We're licensed and insured, and I can show you reviews from nearby customers.",
    )

    assert "insured" in dodge.reaction_intent.lower()
    assert dodge.turn_analysis.missed_pending_test is True
    assert "ignores_objection" in dodge.behavioral_signals
    assert answer.behavioral_signals.count("provides_proof") >= 1
    assert orchestrator.get_state("session-pending-test").pending_test_question is None


# ---------------------------------------------------------------------------
# Signal detection — committed changes (7c5cba9)
# ---------------------------------------------------------------------------

class TestSocialProofSignalDetection:
    """SOCIAL_PROOF_PHRASES → mentions_social_proof signal fires correctly."""

    def setup_method(self):
        self.analyzer = ConversationTurnAnalyzer()
        self.state = ConversationState()

    def _signals(self, text: str) -> list[str]:
        return self.analyzer._evaluate_rep_behavior(text.lower(), text)

    @pytest.mark.parametrize("phrase", SOCIAL_PROOF_PHRASES)
    def test_every_social_proof_phrase_fires_signal(self, phrase: str):
        signals = self._signals(f"We were just working at a {phrase} and thought of you.")
        assert "mentions_social_proof" in signals, (
            f"Expected mentions_social_proof for phrase: {repr(phrase)}"
        )

    def test_social_proof_fires_alongside_rapport(self):
        # Sentence that hits both lists
        signals = self._signals(
            "Hey, how's it going — we were just down the street helping your neighbor."
        )
        assert "mentions_social_proof" in signals
        assert "builds_rapport" in signals

    def test_generic_street_reference_does_not_fire_social_proof(self):
        # Should not trigger on unrelated street mention
        signals = self._signals("I live on Main Street and I'm looking for work.")
        assert "mentions_social_proof" not in signals

    def test_joneses_example_fires_social_proof_via_down_the_street(self):
        signals = self._signals(
            "We're coming from the Joneses house down the street."
        )
        assert "mentions_social_proof" in signals

    def test_next_door_fires_signal(self):
        assert "mentions_social_proof" in self._signals("We just finished a job next door.")

    def test_in_this_neighborhood_fires_signal(self):
        assert "mentions_social_proof" in self._signals(
            "We've been doing work in this neighborhood for a few weeks."
        )


class TestRapportPhraseDetection:
    """Expanded RAPPORT_PHRASES → builds_rapport fires for new entries."""

    def setup_method(self):
        self.analyzer = ConversationTurnAnalyzer()

    def _signals(self, text: str) -> list[str]:
        return self.analyzer._evaluate_rep_behavior(text.lower(), text)

    @pytest.mark.parametrize("phrase", RAPPORT_PHRASES)
    def test_every_rapport_phrase_fires_signal(self, phrase: str):
        signals = self._signals(f"Hi there, {phrase}, nice to meet you.")
        assert "builds_rapport" in signals, (
            f"Expected builds_rapport for phrase: {repr(phrase)}"
        )

    def test_hows_it_going_fires_rapport(self):
        # This was the exact phrase that was failing before the fix
        signals = self._signals("hey how's it going")
        assert "builds_rapport" in signals
        assert "neutral_delivery" not in signals

    def test_sorry_to_bother_fires_rapport(self):
        signals = self._signals("Hey, sorry to bother you, do you have a quick second?")
        assert "builds_rapport" in signals

    def test_hope_not_interrupting_fires_rapport(self):
        signals = self._signals("Hope I'm not interrupting anything.")
        assert "builds_rapport" in signals

    def test_pure_sales_pitch_does_not_fire_rapport(self):
        signals = self._signals("We offer a monthly pest control plan starting at forty nine dollars.")
        assert "builds_rapport" not in signals


class TestReactionIntentSocialProof:
    """_reaction_intent returns neighbor-specific directive when mentions_social_proof fires."""

    def setup_method(self):
        self.orchestrator = ConversationOrchestrator()

    def test_social_proof_reaction_intent_names_the_claim(self):
        self.orchestrator.initialize_session(
            "session-sp-reaction",
            scenario_name="Neighbor Drop",
            scenario_description="Rep mentions a neighbor to break the ice.",
            difficulty=2,
            persona={"attitude": "neutral", "concerns": ["price"]},
            stages=["door_knock", "initial_pitch", "objection_handling"],
        )
        plan = self.orchestrator.prepare_rep_turn(
            "session-sp-reaction",
            "We just wrapped up a job a few houses down and wanted to stop by.",
        )
        intent = plan.reaction_intent.lower()
        # Should reference the specific neighbor/street claim, not just generic rapport
        assert any(word in intent for word in ("neighbor", "down", "street", "nearby", "house"))

    def test_social_proof_reaction_intent_does_not_skip_to_objection(self):
        self.orchestrator.initialize_session(
            "session-sp-no-objection",
            scenario_name="Neighbor Drop Skeptical",
            scenario_description="Skeptical homeowner answers the door.",
            difficulty=3,
            persona={"attitude": "skeptical", "concerns": ["price", "trust"]},
            stages=["door_knock", "initial_pitch", "objection_handling"],
        )
        plan = self.orchestrator.prepare_rep_turn(
            "session-sp-no-objection",
            "Hey, we were working with the Smiths down the street and thought we'd come by.",
        )
        # First turn — should react to the social proof, not immediately surface price or trust
        assert plan.response_plan.allowed_new_objection is None

    def test_generic_greeting_does_not_get_social_proof_reaction(self):
        self.orchestrator.initialize_session(
            "session-generic-greeting",
            scenario_name="Basic Opener",
            scenario_description="Rep just says hi.",
            difficulty=2,
            persona={"attitude": "neutral", "concerns": ["price"]},
            stages=["door_knock", "initial_pitch", "objection_handling"],
        )
        plan = self.orchestrator.prepare_rep_turn(
            "session-generic-greeting",
            "Hey, how's it going?",
        )
        # builds_rapport → first-turn contract path, not social proof path
        assert "mentions_social_proof" not in plan.behavioral_signals
        assert plan.reaction_intent.startswith("This is turn 1.")


class TestDoorOpenStageGuidance:
    """DOOR_OPEN stage guidance: natural first-turn behavior, no interrogation."""

    def setup_method(self):
        self.orchestrator = ConversationOrchestrator()

    def _init(self, session_id: str, difficulty: int = 3, attitude: str = "neutral"):
        self.orchestrator.initialize_session(
            session_id,
            scenario_name="Door Opener",
            scenario_description="A homeowner answers the door.",
            difficulty=difficulty,
            persona={"attitude": attitude, "concerns": ["price"]},
            stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
        )

    def test_simple_greeting_produces_turn1_contract(self):
        self._init("dg-1")
        plan = self.orchestrator.prepare_rep_turn("dg-1", "Hey, how's it going?")
        assert plan.reaction_intent.startswith("This is turn 1.")
        assert plan.response_plan.friction_level <= 1
        assert plan.response_plan.allowed_new_objection is None

    def test_skeptical_high_difficulty_still_respects_turn1_cap(self):
        self._init("dg-2", difficulty=5, attitude="skeptical")
        plan = self.orchestrator.prepare_rep_turn("dg-2", "Good afternoon!")
        # Even difficulty-5 skeptics don't immediately interrogate on turn 1
        assert plan.response_plan.friction_level <= 1
        assert plan.response_plan.allowed_new_objection is None

    def test_early_pitch_attempt_can_raise_friction_on_turn1(self):
        self._init("dg-3", difficulty=4)
        # Rep skips greeting and jumps straight into closing language
        plan = self.orchestrator.prepare_rep_turn(
            "dg-3",
            "Sign today and we'll do a free inspection — right now, let's close this.",
        )
        # pushes_close on turn 1 should override the soft cap
        assert "pushes_close" in plan.behavioral_signals
        # friction should not be soft-capped in this case
        assert plan.response_plan.friction_level >= 2
