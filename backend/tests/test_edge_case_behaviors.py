from app.services.conversation_orchestrator import ConversationOrchestrator


def _build_orchestrator(session_id: str = "edge-case-session") -> ConversationOrchestrator:
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        session_id,
        scenario_name="Edge Case Homeowner",
        scenario_description="A homeowner decides whether to keep listening.",
        difficulty=2,
        persona={"attitude": "guarded", "concerns": ["price"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering", "close_attempt"],
    )
    return orchestrator


def test_no_intro_triggers_on_first_turn_without_name():
    orchestrator = _build_orchestrator("session-no-intro")

    plan = orchestrator.prepare_rep_turn("session-no-intro", "Can I get a minute of your time?")

    assert plan.active_edge_cases == ["no_intro"]


def test_no_intro_does_not_trigger_when_name_given():
    orchestrator = _build_orchestrator("session-with-intro")

    plan = orchestrator.prepare_rep_turn("session-with-intro", "Hi, I'm Alex with Acme Pest Control.")

    assert "no_intro" not in plan.active_edge_cases


def test_premature_close_triggers_before_objection_stage():
    orchestrator = _build_orchestrator("session-premature-close")

    plan = orchestrator.prepare_rep_turn(
        "session-premature-close",
        "Hi, I'm Alex with Acme Pest Control, can we schedule an appointment today?",
    )

    assert "premature_close" in plan.active_edge_cases


def test_ignored_objection_wall_triggers_at_streak_3():
    orchestrator = _build_orchestrator("session-ignored-wall")
    state = orchestrator.get_state("session-ignored-wall")
    state.ignored_objection_streak = 3
    state.stage = "objection_handling"
    state.rep_turns = 1

    plan = orchestrator.prepare_rep_turn(
        "session-ignored-wall",
        "I'm with Acme and wanted to see if you had any questions.",
    )

    assert "ignored_objection_wall" in plan.active_edge_cases


def test_edge_case_layer_included_in_prompt_when_active():
    orchestrator = _build_orchestrator("session-edge-prompt")

    plan = orchestrator.prepare_rep_turn("session-edge-prompt", "Can I get a minute of your time?")

    assert "LAYER 4B - EDGE CASE DIRECTIVES" in plan.system_prompt
    assert "Ask who they are with before engaging further." in plan.system_prompt


def test_edge_case_layer_absent_when_no_cases():
    orchestrator = _build_orchestrator("session-no-edge-prompt")

    plan = orchestrator.prepare_rep_turn(
        "session-no-edge-prompt",
        "Hi, I'm Alex with Acme Pest Control and I appreciate your time.",
    )

    assert "LAYER 4B - EDGE CASE DIRECTIVES" not in plan.system_prompt


def test_spouse_handoff_eligible_triggers_when_considering_and_partner_is_in_concerns():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-spouse-handoff",
        scenario_name="Decision Partner Needed",
        scenario_description="A homeowner wants a spouse involved before deciding.",
        difficulty=2,
        persona={"attitude": "guarded", "concerns": ["wife wants to review this first"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering", "close_attempt"],
    )
    state = orchestrator.get_state("session-spouse-handoff")
    state.stage = "considering"
    state.objection_pressure = 2
    state.rep_turns = 1

    plan = orchestrator.prepare_rep_turn(
        "session-spouse-handoff",
        "I'm with Acme and wanted to answer anything else for you.",
    )

    assert "spouse_handoff_eligible" in plan.active_edge_cases
