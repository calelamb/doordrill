from app.services.conversation_orchestrator import ConversationOrchestrator


def test_starting_emotion_comes_from_persona_and_scenario():
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


def test_acknowledgement_and_value_reduce_resistance():
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
    assert plan.emotion_after == "interested"
    assert "acknowledges_concern" in plan.behavioral_signals
    assert "explains_value" in plan.behavioral_signals
    assert "price" not in plan.active_objections


def test_ignoring_objections_escalates_to_hostile():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-c",
        scenario_name="Busy Homeowner",
        scenario_description="Homeowner is busy and skeptical about switching providers.",
        difficulty=3,
        persona={"attitude": "skeptical", "concerns": ["price", "incumbent_provider"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn("session-c", "Sign today right now. Let's close this.")

    assert plan.stage_after == "close_attempt"
    assert plan.emotion_after == "hostile"
    assert "pushes_close" in plan.behavioral_signals
    assert "ignores_objection" in plan.behavioral_signals


def test_system_prompt_includes_emotion_persona_and_objections():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-d",
        scenario_name="Curious Homeowner",
        scenario_description="A curious homeowner wants to understand the service.",
        difficulty=1,
        persona={"attitude": "curious", "concerns": ["trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn("session-d", "Hello, I appreciate your time and can walk through our local reviews.")

    assert "Current emotional state:" in plan.system_prompt
    assert "Scenario: Curious Homeowner." in plan.system_prompt
    assert "Persona attitude: curious." in plan.system_prompt
    assert "Active unresolved objections:" in plan.system_prompt
