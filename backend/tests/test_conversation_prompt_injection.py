from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
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
