from app.services.micro_behavior_engine import HESITATION_VARIANTS, ConversationalMicroBehaviorEngine


def test_hesitation_metadata_present_for_skeptical_response():
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

    assert plan.transformed_text == "I am not sure that changing providers makes sense for us right now."
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
    assert plan.transformed_text == "We already have someone for that and we are not switching."


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


def test_transformed_text_is_always_equal_to_input():
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

    assert first.transformed_text == "I need a minute to think about that because it is new to me."
    assert second.transformed_text == "I need a minute to think about that because it is new to me."


class TestMetadataOnlyBehavior:
    def test_transformed_text_equals_input(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="I already have a pest control company.",
            emotion_before="neutral",
            emotion_after="skeptical",
            behavioral_signals=[],
            active_objections=["incumbent_provider"],
        )
        assert plan.transformed_text == "I already have a pest control company."

    def test_no_fillers_injected(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="That seems expensive.",
            emotion_before="skeptical",
            emotion_after="annoyed",
            behavioral_signals=[],
            active_objections=["price"],
        )
        assert plan.transformed_text == "That seems expensive."

    def test_no_sentence_truncation(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="I don't think so, we already have someone who comes out.",
            emotion_before="annoyed",
            emotion_after="annoyed",
            behavioral_signals=[],
            active_objections=[],
        )
        assert plan.transformed_text == "I don't think so, we already have someone who comes out."

    def test_still_produces_metadata(self):
        engine = ConversationalMicroBehaviorEngine()
        engine.initialize_session("test-session", persona={})
        plan = engine.apply_to_response(
            session_id="test-session",
            raw_text="What kind of treatment do you use?",
            emotion_before="curious",
            emotion_after="curious",
            behavioral_signals=[],
            active_objections=[],
        )
        assert plan.tone is not None
        assert plan.sentence_length is not None
        assert len(plan.segments) > 0
        assert plan.segments[0].pause_before_ms >= 0
        assert plan.segments[0].tone is not None
