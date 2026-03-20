from app.db.session import SessionLocal
from app.models.transcript import ObjectionType
from app.services.conversation_orchestrator import (
    OBJECTION_KEYWORDS_FALLBACK,
    OBJECTION_RESOLUTION_SIGNALS,
    invalidate_objection_cache,
    load_objection_keywords,
)
from app.voice.ws import homeowner_token_budget


def _objection_type(tag: str, phrases: list[str]) -> ObjectionType:
    return ObjectionType(
        tag=tag,
        display_name=tag.replace("_", " ").title(),
        category="test",
        difficulty_weight=0.5,
        industry="pest_control",
        typical_phrases=list(phrases),
        resolution_techniques=["Acknowledge and clarify"],
        active=True,
    )


def test_load_objection_keywords_returns_db_rows():
    invalidate_objection_cache()
    db = SessionLocal()
    try:
        db.add_all(
            [
                _objection_type("price", ["too expensive"]),
                _objection_type("locked_in_contract", ["under contract"]),
            ]
        )
        db.commit()

        keywords = load_objection_keywords(db)

        assert "price" in keywords
        assert "locked_in_contract" in keywords
    finally:
        db.close()
        invalidate_objection_cache()


def test_load_objection_keywords_falls_back_when_empty():
    invalidate_objection_cache()
    db = SessionLocal()
    try:
        assert load_objection_keywords(db) == OBJECTION_KEYWORDS_FALLBACK
    finally:
        db.close()
        invalidate_objection_cache()


def test_locked_in_contract_resolves_with_correct_signals():
    assert OBJECTION_RESOLUTION_SIGNALS["price_per_month"] == frozenset(
        {"acknowledges_concern", "explains_value", "reduces_pressure"}
    )
    assert OBJECTION_RESOLUTION_SIGNALS["locked_in_contract"] == frozenset(
        {"acknowledges_concern", "explains_value", "invites_dialogue"}
    )
    assert OBJECTION_RESOLUTION_SIGNALS["not_right_now"] == frozenset(
        {"acknowledges_concern", "reduces_pressure", "invites_dialogue"}
    )
    assert OBJECTION_RESOLUTION_SIGNALS["skeptical_of_product"] == frozenset(
        {"acknowledges_concern", "provides_proof", "explains_value"}
    )
    assert OBJECTION_RESOLUTION_SIGNALS["need"] == frozenset(
        {"acknowledges_concern", "explains_value", "personalizes_pitch"}
    )
    assert OBJECTION_RESOLUTION_SIGNALS["decision_authority"] == frozenset(
        {"acknowledges_concern", "reduces_pressure", "invites_dialogue"}
    )


def test_stage_aware_token_budget():
    assert homeowner_token_budget("door_knock") == 30
    assert homeowner_token_budget("considering") == 75
