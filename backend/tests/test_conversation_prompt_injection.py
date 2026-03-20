from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.org_prompt_config import OrgPromptConfig
from app.models.prompt_version import PromptVersion
from app.services.conversation_orchestrator import ConversationOrchestrator, HomeownerPersona, PromptBuilder


@pytest.fixture
def memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


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


def test_prompt_builder_includes_layer_five_override_when_content_is_present():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v2",
        conversation_prompt_content="Ask at least one follow-up question before softening.",
    )

    assert "LAYER 5 - PROMPT OVERRIDE DIRECTIVES" in prompt
    assert "Ask at least one follow-up question before softening." in prompt
    assert prompt.index("LAYER 5 - PROMPT OVERRIDE DIRECTIVES") < prompt.index("RULE: Respond in ONE sentence only.")


def test_prompt_builder_omits_layer_five_override_when_content_is_none():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v1",
        conversation_prompt_content=None,
    )

    assert "LAYER 5 - PROMPT OVERRIDE DIRECTIVES" not in prompt


def test_prompt_builder_uses_sentence_rule_without_word_count_cap():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v1",
    )

    assert "natural and spoken, not formal" in prompt
    assert "Maximum" not in prompt


def test_prompt_builder_includes_layer_zero_when_org_config_is_published():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v1",
        conversation_prompt_content=None,
        org_config=OrgPromptConfig(
            org_id="org-123",
            company_name="Acme Solar",
            product_category="residential solar",
            product_description="Panels and battery backup for homeowners.",
            pitch_stages=["door_knock", "initial_pitch", "close_attempt"],
            unique_selling_points=["Battery backup"],
            known_objections=[],
            target_demographics={"age_range": "35-65", "common_concerns": ["cost", "installation"]},
            competitors=[],
            pricing_framing="Site survey first.",
            close_style="consultative",
            rep_tone_guidance="professional_warm",
            grading_priorities=["rapport_building"],
            published=True,
        ),
    )

    assert "=== COMPANY CONTEXT ===" in prompt
    assert "Acme Solar" in prompt
    assert prompt.index("=== COMPANY CONTEXT ===") < prompt.index("LAYER 1 - IMMERSION CONTRACT")


def test_bind_session_context_loads_prompt_content_from_matching_prompt_version(memory_db):
    memory_db.add(
        PromptVersion(
            prompt_type="conversation",
            version="conversation_v2",
            content="Use one follow-up question before returning to objection mode.",
            active=True,
        )
    )
    memory_db.commit()

    orchestrator = ConversationOrchestrator()
    orchestrator.bind_session_context(
        session_id="session-override-test",
        scenario=None,
        prompt_version="conversation_v2",
        db=memory_db,
    )

    context = orchestrator._contexts["session-override-test"]
    assert context.conversation_prompt_content == "Use one follow-up question before returning to objection mode."


def test_prompt_builder_trims_layer_4b_when_prompt_exceeds_hard_limit():
    builder = PromptBuilder()
    prompt = builder.build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v2",
        conversation_prompt_content="pricing proof " * 2200,
        active_edge_cases=["premature_close"],
    )

    assert "LAYER 4B - EDGE CASE DIRECTIVES" not in prompt
    assert builder.last_token_count > 0


def test_prepare_rep_turn_updates_system_prompt_token_count_on_session_state():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-token-count",
        scenario_name="Skeptical Homeowner",
        scenario_description="Rep handles monthly service concerns.",
        difficulty=2,
        persona={"attitude": "skeptical", "concerns": ["price", "trust"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    )

    orchestrator.prepare_rep_turn(
        "session-token-count",
        "Hi, I understand price matters and I appreciate your time. We can save you money.",
    )

    payload = orchestrator.get_state_payload("session-token-count")
    assert payload["system_prompt_token_count"] > 0


def test_prompt_builder_includes_transcript_quality_guardrails():
    prompt = PromptBuilder().build(
        scenario=None,
        persona=_persona(),
        stage="objection_handling",
        prompt_version="conversation_v1",
        latest_rep_text="So are you saying the monthly plan starts today?",
        transcript_quality={
            "quality_band": "low",
            "confidence": 0.58,
            "applied_terms": ["monthly plan"],
        },
        active_objections=["price"],
        response_plan=None,
    )

    assert "LAYER 3A-QUALITY - TRANSCRIPT QUALITY" in prompt
    assert "Latest rep utterance to answer first: So are you saying the monthly plan starts today?" in prompt
    assert "ask one short homeowner clarification question" in prompt
    assert "Do not invent a competitor, promise, price, or service detail" in prompt


def test_prepare_rep_turn_threads_transcript_quality_into_system_prompt():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "session-transcript-quality",
        scenario_name="Guarded Homeowner",
        scenario_description="Rep is explaining a monthly pest control plan.",
        difficulty=3,
        persona={"attitude": "skeptical", "concerns": ["price", "timing"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering", "close_attempt"],
    )

    plan = orchestrator.prepare_rep_turn(
        "session-transcript-quality",
        "So the monthly plan would cover the outside first.",
        transcript_quality={
            "quality_band": "medium",
            "confidence": 0.74,
            "applied_terms": ["monthly plan"],
        },
    )

    assert "LAYER 3A-QUALITY - TRANSCRIPT QUALITY" in plan.system_prompt
    assert "Latest rep utterance to answer first: So the monthly plan would cover the outside first." in plan.system_prompt
    assert "Semantic anchors to preserve" in plan.system_prompt
