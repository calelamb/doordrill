from app.services.conversation_orchestrator import ConversationOrchestrator, HomeownerPersona, PersonaEnricher


def _persona(**overrides) -> HomeownerPersona:
    payload = {
        "name": "Jordan",
        "attitude": "guarded",
        "concerns": ["price"],
        "objection_queue": [],
        "buy_likelihood": "medium",
        "softening_condition": "Specific, calm answers help.",
    }
    payload.update(overrides)
    return HomeownerPersona(**payload)


def test_enricher_fills_missing_fields_for_difficulty_1():
    persona = _persona()

    enriched = PersonaEnricher.enrich(persona, 1, "A calm homeowner has not had pest issues lately.")

    assert enriched.household_type == "homeowner"
    assert enriched.home_ownership_years == 12
    assert enriched.pest_history == ["rarely notices pest issues around the home"]
    assert enriched.price_sensitivity == "medium"
    assert enriched.communication_style == "terse"


def test_enricher_fills_missing_fields_for_difficulty_5():
    persona = _persona(attitude="hostile")

    enriched = PersonaEnricher.enrich(persona, 5, "The homeowner is frustrated about recurring ants.")

    assert enriched.household_type == "homeowner"
    assert enriched.home_ownership_years == 2
    assert enriched.pest_history == ["has dealt with recurring ants recently", "has tried DIY fixes before"]
    assert enriched.price_sensitivity == "high"
    assert enriched.communication_style == "confrontational"


def test_enricher_preserves_explicit_fields():
    persona = _persona(
        household_type="retired couple",
        home_ownership_years=23,
        pest_history=["had termites five years ago"],
        price_sensitivity="low",
        communication_style="analytical",
    )

    enriched = PersonaEnricher.enrich(persona, 5, "The homeowner is upset about recurring pests.")

    assert enriched.household_type == "retired couple"
    assert enriched.home_ownership_years == 23
    assert enriched.pest_history == ["had termites five years ago"]
    assert enriched.price_sensitivity == "low"
    assert enriched.communication_style == "analytical"


def test_household_type_inferred_from_kids_concern():
    persona = _persona(concerns=["worried about kids and chemicals"])

    enriched = PersonaEnricher.enrich(persona, 2, "A cautious homeowner is listening.")

    assert enriched.household_type == "family with kids"


def test_persona_enriched_fields_appear_in_system_prompt():
    orchestrator = ConversationOrchestrator()
    orchestrator.initialize_session(
        "persona-prompt-session",
        scenario_name="Recurring Ant Concern",
        scenario_description="A skeptical homeowner is dealing with recurring ants.",
        difficulty=5,
        persona={"attitude": "skeptical", "concerns": ["price"]},
        stages=["door_knock", "initial_pitch", "objection_handling", "considering"],
    )

    prompt = orchestrator._build_system_prompt("door_knock", session_id="persona-prompt-session")

    assert "Household: homeowner" in prompt
    assert "Owned home for: 2 years" in prompt
    assert "Pest history: has dealt with recurring ants recently, has tried DIY fixes before" in prompt
    assert "Price sensitivity: high" in prompt
    assert "Communication style: analytical - respond accordingly." in prompt
