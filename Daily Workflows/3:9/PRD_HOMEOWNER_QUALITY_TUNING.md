# DoorDrill — Homeowner Simulation Quality Tuning
## Phase Suite: QH1 → QH2 → QH3

**Version:** 1.0
**Status:** Ready for Codex implementation
**Context:** Full infrastructure suite (TP1–T4, R1–R7, PM1–PM6, C1–C4) is complete.
This suite tunes the live homeowner simulation for realism, objection depth, and edge case coverage.

---

## Why This Suite

The homeowner simulation engine has a solid state machine foundation but three critical quality gaps:

1. **TP3 objection taxonomy is orphaned** — 10 D2D pest control objection types were seeded in the DB but the orchestrator still uses a 6-type hardcoded dict. New types (price_per_month, locked_in_contract, decision_authority, etc.) never surface during drills.
2. **Token budget is flat** — `HOMEOWNER_MAX_TOKENS = 30` applies equally to a door knock ("Who are you?") and a close window ("I'd need to talk to my wife, but the price seems okay..."). Stage-aware budgets make responses feel real.
3. **Edge case behaviors are thin** — No specific triggers for: rep skips intro, premature close attempt, spouse handoff, 3+ ignored objections → door close warning.

Build in order. Each phase is independently deployable.

---

## Phase Catalog

| Phase | File | Focus |
|-------|------|-------|
| QH1 | This file | Wire TP3 taxonomy + stage-aware token budget |
| QH2 | This file | Edge case escalation behaviors |
| QH3 | This file | Richer persona backstory generation |
| QH4 | This file | RAG-backed company context injection |

---

## Codex Execution Guide

1. Paste `BOOTSTRAP_PROMPT.md` contents first in every Codex thread.
2. Paste the phase prompt below.
3. After each phase: `cd backend && python -m pytest tests/ -x -q`
4. Commit before moving to the next phase.

---

## Paste-Ready Phase Prompts

---

### PHASE QH1 — Objection Taxonomy Bridge + Stage-Aware Token Budget

```
Bootstrap is loaded. The full infrastructure suite (TP1–T4, R1–R7, C1–C4) is complete.
We are now tuning the homeowner simulation quality. Implement Phase QH1.

Files to read first:
- backend/app/services/conversation_orchestrator.py (full file)
- backend/app/models/transcript.py (ObjectionType model)

Goals:

1. OBJECTION TAXONOMY BRIDGE
   In conversation_orchestrator.py, replace the hardcoded OBJECTION_KEYWORDS dict with
   a module-level loader function load_objection_keywords(db: Session) -> dict[str, tuple[str, ...]].
   - Query all active ObjectionType rows (ObjectionType.is_active == True).
   - Build the dict keyed by ObjectionType.slug, value = tuple(ObjectionType.trigger_keywords).
   - Cache the result in a module-level _OBJECTION_KEYWORDS_CACHE: dict | None = None.
   - Add invalidate_objection_cache() to clear it (for tests and migrations).
   - Keep the existing hardcoded OBJECTION_KEYWORDS dict as OBJECTION_KEYWORDS_FALLBACK —
     used when the DB query returns zero rows or raises.

2. WIRE THE LOADER
   In ConversationOrchestrator._extract_objection_tags(rep_text, db=None):
   - Add an optional db: Session | None = None parameter.
   - When db is provided, call load_objection_keywords(db).
   - Fall back to OBJECTION_KEYWORDS_FALLBACK when db is None.
   Update all callers in ws.py (prepare_rep_turn call site) to pass the active db session.

3. EXPAND OBJECTION_RESOLUTION_SIGNALS
   The current dict only covers 6 types. Extend it to cover all 10 TP3 types:
   - price_per_month: frozenset({"acknowledges_concern", "explains_value", "reduces_pressure"})
   - locked_in_contract: frozenset({"acknowledges_concern", "explains_value", "invites_dialogue"})
   - not_right_now: frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"})
   - skeptical_of_product: frozenset({"acknowledges_concern", "provides_proof", "explains_value"})
   - need: frozenset({"acknowledges_concern", "explains_value", "personalizes_pitch"})
   - decision_authority: frozenset({"acknowledges_concern", "reduces_pressure", "invites_dialogue"})

4. STAGE-AWARE TOKEN BUDGET
   In ws.py, replace the module-level HOMEOWNER_MAX_TOKENS = 30 constant with a function:
   def homeowner_token_budget(stage: str) -> int:
       STAGE_BUDGETS = {
           "door_knock": 15,
           "initial_pitch": 28,
           "objection_handling": 30,
           "considering": 45,
           "close_attempt": 40,
           "ended": 12,
       }
       return STAGE_BUDGETS.get(stage, 28)
   Update the PromptBuilder hard_rule to use the stage-appropriate word cap:
     door_knock/ended = "Maximum 10 words."
     listening/objecting = "Maximum 20 words."
     considering/close_attempt = "Maximum 30 words. You may think out loud briefly."
   Pass the current stage into the token budget call at the LLM invoke site.

5. TESTS
   Write backend/tests/test_objection_taxonomy_bridge.py:
   - test_load_objection_keywords_returns_db_rows: seed 2 ObjectionType rows, call
     load_objection_keywords(db), assert returned dict contains both slugs.
   - test_load_objection_keywords_falls_back_when_empty: empty DB, assert returns
     OBJECTION_KEYWORDS_FALLBACK.
   - test_locked_in_contract_resolves_with_correct_signals: verify OBJECTION_RESOLUTION_SIGNALS
     contains the new types.
   - test_stage_aware_token_budget: assert homeowner_token_budget("door_knock") == 15,
     homeowner_token_budget("considering") == 45.

6. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE QH2 — Edge Case Escalation Behaviors

```
Bootstrap is loaded. Phase QH1 is complete.
Implement Phase QH2: edge case escalation behaviors.

Files to read first:
- backend/app/services/conversation_orchestrator.py (full file — especially prepare_rep_turn,
  _build_system_prompt, PromptBuilder.build)

Goals:

1. EDGE CASE TRIGGER DETECTION
   Add _detect_edge_cases(rep_text: str, state: ConversationState, turn_number: int) -> list[str]
   to ConversationOrchestrator. Returns a list of triggered edge case tags (may be empty).
   Implement detection for:
   - "no_intro": turn_number == 1 and none of ("my name", "i'm", "i am", "with") in rep_text.lower()
   - "premature_close": close language detected (sign, schedule, appointment, set up)
     before stage reaches "objection_handling" or later.
   - "ignored_objection_wall": state.ignored_objection_streak >= 3
   - "spouse_handoff_eligible": stage == "considering" and state.objection_pressure <= 2
     and "husband" or "wife" or "partner" or "spouse" in persona concerns

2. WIRE INTO prepare_rep_turn
   Call _detect_edge_cases() at the top of prepare_rep_turn().
   Store active edge case tags in state.active_edge_cases: list[str] (add field to ConversationState).
   Include them in the RepTurnPlan (add active_edge_cases: list[str] field).

3. EDGE CASE LAYER IN PROMPT BUILDER
   Add a new LAYER 4B — EDGE CASE DIRECTIVES section in PromptBuilder.build().
   Only include this layer when active_edge_cases is non-empty.
   Map edge case tags to prompt directives:
   - "no_intro" → "The rep did not introduce themselves or their company. Ask who they are
     with before engaging further. Do not discuss pest control until they answer."
   - "premature_close" → "The rep is trying to close before you understand the offer.
     Express confusion or mild pushback: 'I don't even know what you're selling yet.'"
   - "ignored_objection_wall" → "You have raised concerns that the rep keeps ignoring.
     Firmly state you need to go and do not reopen the conversation this turn."
   - "spouse_handoff_eligible" → "You are considering but not ready to decide alone.
     Tell the rep your partner would need to be part of this conversation."
   Pass active_edge_cases into build() and include LAYER 4B between LAYER 4 and the closing rule.

4. EMIT EDGE CASE EVENTS
   In ws.py, after calling prepare_rep_turn(), if plan.active_edge_cases is non-empty,
   emit a new "server.edge_case.triggered" WebSocket event:
   { "type": "server.edge_case.triggered", "tags": plan.active_edge_cases }
   This is informational only (client can log it for analytics).

5. TESTS
   Write backend/tests/test_edge_case_behaviors.py:
   - test_no_intro_triggers_on_first_turn_without_name
   - test_no_intro_does_not_trigger_when_name_given
   - test_premature_close_triggers_before_objection_stage
   - test_ignored_objection_wall_triggers_at_streak_3
   - test_edge_case_layer_included_in_prompt_when_active
   - test_edge_case_layer_absent_when_no_cases

6. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE QH3 — Richer Persona Backstory

```
Bootstrap is loaded. Phase QH2 is complete.
Implement Phase QH3: richer persona generation for more realistic homeowner simulation.

Files to read first:
- backend/app/services/conversation_orchestrator.py (HomeownerPersona, PromptBuilder.build, Layer 2)
- backend/app/models/scenario.py (Scenario model, persona field structure)

Goals:

1. EXPAND HomeownerPersona DATACLASS
   Add new optional fields to HomeownerPersona:
   - household_type: str  (e.g., "family with kids", "retired couple", "single homeowner")
   - home_ownership_years: int  (1–30)
   - pest_history: list[str]  (e.g., ["had ants last summer", "never had a pest problem"])
   - price_sensitivity: str  ("low", "medium", "high")
   - communication_style: str  ("terse", "chatty", "confrontational", "analytical")
   All default to None / empty list.
   Update from_payload() to parse these fields if present.

2. PERSONA ENRICHMENT DEFAULTS
   Add PersonaEnricher.enrich(persona: HomeownerPersona, difficulty: int,
   scenario_description: str) -> HomeownerPersona.
   When a field is None, assign a realistic default based on:
   - difficulty 1–2: friendly/terse, low pest history, medium price sensitivity, 5–15 ownership years
   - difficulty 3: neutral/chatty, light pest history, medium price sensitivity
   - difficulty 4–5: confrontational/analytical, active pest history, high price sensitivity, shorter ownership
   - household_type: infer from attitude keywords ("family" if concerns contain "kids"/"family",
     else "homeowner")
   Return an enriched copy — do not mutate the original.
   Call enrich() in ConversationOrchestrator._initialize_state_from_context() after parsing persona.

3. WIRE INTO PROMPT BUILDER LAYER 2
   Update PromptBuilder.build() to accept the enriched persona and include new fields in LAYER 2:
   - If household_type set: "Household: {household_type}"
   - If home_ownership_years set: "Owned home for: {home_ownership_years} years"
   - If pest_history non-empty: "Pest history: {', '.join(pest_history)}"
   - If price_sensitivity set: "Price sensitivity: {price_sensitivity}"
   - If communication_style set: "Communication style: {communication_style} — respond accordingly."
   These lines are injected only when the field is populated (no "none" padding).

4. SCENARIO PERSONA STORAGE
   Managers can already configure persona JSON on a Scenario. Ensure the Scenario.persona dict
   can accept the new fields (no migration needed — they're parsed from existing JSON).
   Document the accepted keys in a comment block at the top of HomeownerPersona.from_payload().

5. TESTS
   Write backend/tests/test_persona_enrichment.py:
   - test_enricher_fills_missing_fields_for_difficulty_1
   - test_enricher_fills_missing_fields_for_difficulty_5
   - test_enricher_preserves_explicit_fields
   - test_household_type_inferred_from_kids_concern
   - test_persona_enriched_fields_appear_in_system_prompt

6. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE QH4 — RAG-backed Company Context Injection

```
Bootstrap is loaded. Phase QH3 is complete.
Implement Phase QH4: inject org knowledge base documents into the live homeowner simulation.

Context: DocumentRetrievalService already powers grading (retrieves methodology context) and
manager AI coaching (retrieves rep insight context). The homeowner simulation — conversation_orchestrator.py
and ws.py — has never used it. This phase changes that.

When an org uploads documents (pricing sheets, product specs, competitor comparisons, FAQ),
the homeowner should be able to reference company-specific details during the drill:
"I think I saw on your website you charge $89 a month" or "Your competitor Terminix has a
better deal" — making objections feel grounded rather than generic.

Files to read first:
- backend/app/services/conversation_orchestrator.py (SessionPromptContext, PromptBuilder.build,
  bind_session_context signature)
- backend/app/services/document_retrieval_service.py (has_ready_documents, retrieve_for_topic,
  format_for_prompt — full signatures and return types)
- backend/app/voice/ws.py (bind_session_context call site around line 152, DB access pattern,
  asyncio usage)

Goals:

1. ADD company_context FIELD TO SessionPromptContext
   Add company_context: str | None = None to the SessionPromptContext dataclass.
   Add company_context: str | None = None parameter to bind_session_context().
   Store it on the context object. No other orchestrator changes needed yet.

2. RETRIEVE AT SESSION INITIALIZATION IN ws.py
   In the section of ws.py that calls orchestrator.bind_session_context() (around line 152),
   add a RAG retrieval step BEFORE the bind call:

   a. Instantiate DocumentRetrievalService(settings=settings) (settings is already imported).
   b. Check: if retrieval_service.has_ready_documents(db, org_id=rep.org_id):
      Run two retrieve_for_topic() calls and combine the results (dedup by chunk_id):
        - Pass 1 (services/pricing): topic="pest control services pricing monthly plan what is
          included coverage", context_hint=scenario.name if scenario else "", k=3, min_score=0.65
        - Pass 2 (competitors/objections): topic="competitor comparison why choose us reviews
          common objections", context_hint=scenario.name if scenario else "", k=2, min_score=0.65
      Format combined chunks with format_for_prompt(chunks, max_tokens=600).
   c. If has_ready_documents() is False or retrieval returns no chunks, company_context = None.
   d. retrieve_for_topic() is synchronous. Call it with:
        loop = asyncio.get_event_loop()
        company_context = await loop.run_in_executor(
            None, lambda: retrieval_service.retrieve_for_topic(...)
        )
      (Do both passes this way, each in its own run_in_executor call.)
   e. Wrap the entire retrieval block in try/except Exception — log a warning and set
      company_context = None on any failure. Never let RAG failure abort session init.
   f. Pass company_context into bind_session_context().

3. INJECT AS LAYER 5 IN PromptBuilder
   In PromptBuilder.build(), add company_context: str | None = None parameter.
   When company_context is non-empty, add LAYER 5 between LAYER 4 and the closing hard_rule:

   LAYER 5 - COMPANY CONTEXT (only included when company_context is not None/empty)
   -------------------------------------------------------------------------------
   "LAYER 5 - WHAT YOU MAY KNOW ABOUT THIS COMPANY\n"
   "Before they knocked, you may have encountered this company through a flyer, neighbor
    mention, or a quick online search. The following is what you found. Use it to make
    your objections specific and grounded — but speak naturally, not like you memorized it.
    Express uncertainty where appropriate ('I think I saw...', 'Someone mentioned...').\n\n"
   + company_context

   Do NOT include LAYER 5 when company_context is None or empty string.
   Update the return statement to include LAYER 5 when present.

   Also update _build_system_prompt() in ConversationOrchestrator to pass
   context.company_context into the build() call.

4. EMIT A SESSION EVENT
   After session init in ws.py, if company_context is not None, emit:
   { "type": "server.session.rag_context_loaded", "payload": { "chunks_loaded": N } }
   where N is the count of retrieved chunks. This lets clients know the homeowner has
   company-specific context without exposing the actual content.

5. TESTS
   Write backend/tests/test_rag_homeowner_injection.py:

   test_company_context_injected_into_prompt_when_documents_exist:
   - Seed a KnowledgeBaseDocument and chunk for the test org.
   - Monkeypatch DocumentRetrievalService.has_ready_documents to return True.
   - Monkeypatch DocumentRetrievalService.retrieve_for_topic to return 2 fake chunks.
   - Run a WS session with mock providers.
   - Capture the system_prompt from the LLM mock (read the system_prompt arg passed to
     MockLlmClient.stream_reply).
   - Assert "LAYER 5" and "WHAT YOU MAY KNOW" appear in the system_prompt.

   test_company_context_absent_when_no_documents:
   - Monkeypatch has_ready_documents to return False.
   - Run a WS session. Assert "LAYER 5" does NOT appear in any system_prompt.

   test_rag_failure_does_not_abort_session:
   - Monkeypatch retrieve_for_topic to raise Exception("retrieval failed").
   - Run a WS session. Assert session connects and first turn completes without error.
   - Assert "LAYER 5" does NOT appear in the system_prompt (graceful fallback).

   test_rag_context_loaded_event_emitted_when_chunks_found:
   - Monkeypatch to return 3 chunks.
   - Run WS session init.
   - Assert server emits server.session.rag_context_loaded with chunks_loaded == 3.

6. Run pytest tests/ -x -q. All tests must pass.
```

---

## Commit Messages

```
feat(simulation): QH1 — wire TP3 objection taxonomy + stage-aware token budget
feat(simulation): QH2 — edge case escalation behaviors
feat(simulation): QH3 — richer persona backstory generation
feat(simulation): QH4 — RAG-backed company context injection into homeowner prompt
```

---

## What Gets Better After Each Phase

- **After QH1**: Drills will surface price_per_month, locked_in_contract, decision_authority
  objections for the first time. Homeowner responses get longer during "considering" stage.
- **After QH2**: Reps who skip their intro get called out immediately. Premature closers get
  shut down. Reps who ignore objections 3x in a row hit a wall. Spouse handoff fires in close
  scenarios.
- **After QH3**: Every homeowner feels like a distinct person — a retired couple responds
  differently than a single homeowner with young kids. Pest history gives the AI natural
  talking points to react to.
- **After QH4**: The homeowner becomes company-aware. "I think I saw online you charge $89 a
  month — is that right?" or "A neighbor mentioned you guys but I couldn't find many reviews."
  Objections are now grounded in your actual product, pricing, and competitive position instead
  of generic AI guesses. Every org gets a different homeowner based on what they've uploaded.
