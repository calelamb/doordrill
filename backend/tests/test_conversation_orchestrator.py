from app.services.conversation_orchestrator import ConversationOrchestrator


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
    assert plan.reaction_intent.startswith("React to the rep first")
    assert plan.turn_analysis.objection_status == "partial"
    assert plan.response_plan.allowed_new_objection == "trust"
    assert plan.response_plan.friction_level >= 2


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
    assert "ignores_objection" in plan.behavioral_signals
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
    assert first_plan.response_plan.wording_rotation_hint is not None
    assert second_plan.response_plan.wording_rotation_hint is not None
    assert first_plan.response_plan.wording_rotation_hint != second_plan.response_plan.wording_rotation_hint
