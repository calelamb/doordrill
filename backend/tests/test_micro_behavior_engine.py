from app.services.micro_behavior_engine import HESITATION_VARIANTS, ConversationalMicroBehaviorEngine


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

    assert any(plan.transformed_text.startswith(variant) for variant in HESITATION_VARIANTS["skeptical"])
    assert any(behavior == "hesitation_mode" for behavior in plan.behaviors)
    assert any("tone:" in behavior for behavior in plan.behaviors)
    assert 300 <= plan.pause_profile["opening_pause_ms"] <= 450
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
    interested_plan = engine.apply_to_response(
        session_id="session-3",
        raw_text="Okay, what would the process actually look like if I wanted to learn more about it?",
        emotion_before="curious",
        emotion_after="interested",
        behavioral_signals=["acknowledges_concern", "explains_value"],
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
    assert interested_plan.pause_profile["opening_pause_ms"] > 400
    assert hostile_plan.sentence_length == "short"
    assert hostile_plan.pause_profile["opening_pause_ms"] < 100


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


def test_curious_turns_do_not_use_hesitation_openers():
    engine = ConversationalMicroBehaviorEngine()
    engine.initialize_session("session-curious", persona={"attitude": "curious"})

    plan = engine.apply_to_response(
        session_id="session-curious",
        raw_text="What would the process look like if we actually switched over next month?",
        emotion_before="neutral",
        emotion_after="curious",
        behavioral_signals=["neutral_delivery", "acknowledges_concern"],
        active_objections=["timing"],
    )

    assert not any(plan.transformed_text.startswith(variant) for variant in HESITATION_VARIANTS["curious"])


def test_trailing_off_is_blocked_when_filler_or_interruption_is_present():
    engine = ConversationalMicroBehaviorEngine()

    assert engine._should_trail_off(
        session_id="session-trailing",
        emotion_after="skeptical",
        sentence_length="medium",
        turn_count=1,
        interruption_type=None,
        filler_used=True,
    ) is False
    assert engine._should_trail_off(
        session_id="session-trailing",
        emotion_after="skeptical",
        sentence_length="medium",
        turn_count=1,
        interruption_type="homeowner_cuts_off_rep",
        filler_used=False,
    ) is False


def test_short_turns_stay_single_segment_even_with_hesitation():
    engine = ConversationalMicroBehaviorEngine()
    engine.initialize_session("session-short", persona={"attitude": "skeptical"})

    plan = engine.apply_to_response(
        session_id="session-short",
        raw_text="I need to think about that first.",
        emotion_before="neutral",
        emotion_after="skeptical",
        behavioral_signals=["neutral_delivery"],
        active_objections=["price"],
    )

    assert plan.sentence_length == "short"
    assert len(plan.segments) == 1
