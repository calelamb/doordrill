from app.services.micro_behavior_engine import ConversationalMicroBehaviorEngine


def test_hesitation_and_filler_are_injected_for_skeptical_response():
    engine = ConversationalMicroBehaviorEngine()
    engine.initialize_session("session-1", persona={"attitude": "skeptical"})

    plan = engine.apply_to_response(
        session_id="session-1",
        raw_text="I am not sure that changing providers makes sense for us right now.",
        emotion_before="neutral",
        emotion_after="skeptical",
        behavioral_signals=["neutral_delivery"],
        active_objections=["incumbent_provider"],
    )

    assert plan.transformed_text.startswith(("Uh...", "Well...", "I mean..."))
    assert any(behavior == "hesitation_mode" for behavior in plan.behaviors)
    assert any("tone:" in behavior for behavior in plan.behaviors)
    assert plan.realism_score >= 6.0


def test_interruptive_behavior_is_used_when_homeowner_is_hostile():
    engine = ConversationalMicroBehaviorEngine()
    engine.initialize_session("session-2", persona={"attitude": "hostile"})

    plan = engine.apply_to_response(
        session_id="session-2",
        raw_text="We already have someone for that and we are not switching.",
        emotion_before="annoyed",
        emotion_after="hostile",
        behavioral_signals=["ignores_objection", "pushes_close"],
        active_objections=["incumbent_provider"],
    )

    assert plan.interruption_type == "homeowner_cuts_off_rep"
    assert any(behavior == "homeowner_cuts_off_rep" for behavior in plan.behaviors)
    assert plan.tone in {"cutting", "confrontational", "sharp"}
    assert plan.sentence_length == "short"


def test_sentence_length_and_pause_profiles_vary_by_emotion():
    engine = ConversationalMicroBehaviorEngine()
    engine.initialize_session("session-3", persona={"attitude": "curious"})

    curious_plan = engine.apply_to_response(
        session_id="session-3",
        raw_text="What would actually change for my home if we started this service and how soon would someone come out?",
        emotion_before="interested",
        emotion_after="curious",
        behavioral_signals=["acknowledges_concern"],
        active_objections=["timing"],
    )
    hostile_plan = engine.apply_to_response(
        session_id="session-3",
        raw_text="I do not want to keep talking about this if you are going to pressure me.",
        emotion_before="skeptical",
        emotion_after="hostile",
        behavioral_signals=["dismisses_concern"],
        active_objections=["price"],
    )

    assert curious_plan.sentence_length == "long"
    assert curious_plan.pause_profile["opening_pause_ms"] >= 300
    assert hostile_plan.sentence_length == "short"
    assert hostile_plan.pause_profile["opening_pause_ms"] <= 140


def test_recent_variants_are_not_reused_immediately():
    engine = ConversationalMicroBehaviorEngine()
    engine.initialize_session("session-4", persona={"attitude": "neutral"})

    first = engine.apply_to_response(
        session_id="session-4",
        raw_text="I need a minute to think about that because it is new to me.",
        emotion_before="neutral",
        emotion_after="neutral",
        behavioral_signals=["neutral_delivery"],
        active_objections=["trust"],
    )
    second = engine.apply_to_response(
        session_id="session-4",
        raw_text="I need a minute to think about that because it is new to me.",
        emotion_before="neutral",
        emotion_after="neutral",
        behavioral_signals=["neutral_delivery"],
        active_objections=["trust"],
    )

    assert first.transformed_text != second.transformed_text
