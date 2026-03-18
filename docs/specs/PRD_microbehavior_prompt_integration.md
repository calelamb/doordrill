# PRD: MicroBehaviorPlan System Prompt Integration

**Status:** Ready for implementation
**Scope:** Backend only — `backend/app/services/conversation_orchestrator.py`, `backend/app/voice/ws.py`
**Dependencies:** Completed PromptVersion wiring (PRD_prompt_version_runtime.md)

---

## Background

The `ConversationalMicroBehaviorEngine` computes a `MicroBehaviorPlan` per AI turn, producing:
- `tone` — e.g., guarded, sharp, warming, exploratory
- `sentence_length` — short / medium / long
- `interruption_type` — whether the homeowner cuts the rep off
- `behaviors` — list of descriptors (tone_shift, hesitation_mode, objection_aware, etc.)
- `pause_profile` — millisecond pause timing per segment
- `transformed_text` — the LLM output with hesitations/fillers injected

The engine's `transformed_text` is what gets sent to TTS. The plan metadata is stored in the `server.turn.committed` event and later written to `SessionTurn.mb_*` columns by `TurnEnrichmentService`.

**The gap:** The engine runs *after* the LLM generates its response. The LLM has no knowledge of what tone, length, or behavioral posture the engine will impose. The engine might decide to cut a warm multi-sentence response down to one curt word — but the LLM wrote it warmly. This creates a mismatch: the *text content* of the response reflects one emotional state, while the *delivery* (trimmed, interrupted, hesitation-laden) reflects another. The homeowner feels incoherent.

**The fix has two parts:**

1. **Pre-inject behavioral directives into the system prompt** — before the LLM call, compute the planned `tone`, `sentence_length`, and `interruption_type` from the current orchestrator state and explicitly instruct the LLM to write in that mode. The LLM then generates text that is *already aligned* with what the engine will deliver, rather than fighting it.

2. **Pass the previous turn's MicroBehaviorPlan as behavioral continuity context** — so the LLM knows what emotional register it was just expressing and can maintain consistency across turns.

---

## Goals

1. Pre-compute behavioral parameters (tone, sentence_length, interruption mode) from current state before the LLM call and inject as a dedicated directive layer in the system prompt.
2. Carry the last AI turn's MicroBehaviorPlan on the `ConversationContext` so the next LLM call can reference what the homeowner just expressed.
3. Store the injected directives in the `server.session.state` event for replay/debug visibility.
4. Keep the engine's `apply_to_response()` post-processing intact — it still handles hesitation/filler text insertion. The pre-injection only sets *intent* constraints.

---

## Non-Goals

- Do not remove or replace the existing `apply_to_response()` post-processing.
- Do not restructure the existing PromptBuilder layers 1–4.
- No database schema changes needed.
- No mobile or dashboard changes.

---

## Task 1: Pre-Computation of Behavioral Directives

**File:** `backend/app/services/conversation_orchestrator.py`

### 1a. Add a `BehaviorDirectives` dataclass

```python
@dataclass
class BehaviorDirectives:
    tone: str
    sentence_length: str
    interruption_mode: bool  # True = homeowner should cut off rep
    directive_text: str      # the formatted string for injection into the prompt
```

### 1b. Add `compute_behavior_directives()` to `ConversationOrchestrator`

This method takes the current state snapshot (emotion_after from the RepTurnPlan, behavioral_signals, active_objections) and produces the directives that the micro-behavior engine *would* compute — but without requiring the raw LLM text yet.

Logic mirrors the existing engine methods:

```python
def compute_behavior_directives(
    self,
    *,
    emotion_before: str,
    emotion_after: str,
    behavioral_signals: list[str],
    active_objections: list[str],
) -> BehaviorDirectives:
```

Tone derivation:
- Use `TONE_BY_TRANSITION`, `DEFAULT_TONE_BY_EMOTION`, and behavioral signal overrides from `micro_behavior_engine.py` exactly. Import those constants; do not duplicate them.

Sentence length derivation:
- Use `SENTENCE_LENGTH_BY_EMOTION` and signal overrides from the engine. Import, do not duplicate.

Interruption mode:
- `emotion_after in {"annoyed", "hostile"}` AND any of `{"ignores_objection", "pushes_close", "dismisses_concern"}` in behavioral_signals.

Format `directive_text` as:
```
LAYER 3C - BEHAVIORAL DIRECTIVES
Tone for this response: {tone}. Write in this register throughout.
Response length: {sentence_length}. {"One sentence only." if short else "Two sentences max." if medium else "Up to three sentences."}
{f"Interrupt the rep: Begin your response cutting off whatever they were saying. Use an opener like 'Hold on,' or 'Wait,' or 'Look,'." if interruption_mode else ""}
Do not exceed these constraints. The delivery will match exactly what you write.
```

### 1c. Add `last_mb_plan` to `ConversationContext`

```python
@dataclass
class ConversationContext:
    ...
    last_mb_plan: dict[str, Any] | None = None  # serialized MicroBehaviorPlan from prior AI turn
```

When the WebSocket commits an AI turn (after `apply_to_response()` runs), update the context:

```python
context.last_mb_plan = {
    "tone": plan.tone,
    "sentence_length": plan.sentence_length,
    "interruption_type": plan.interruption_type,
    "behaviors": plan.behaviors,
    "realism_score": plan.realism_score,
}
```

### 1d. Extend `PromptBuilder.build()` with `behavior_directives` and `last_mb_context`

Add two new optional parameters:

```python
def build(
    self,
    ...,
    behavior_directives: "BehaviorDirectives | None" = None,   # NEW
    last_mb_context: dict[str, Any] | None = None,            # NEW
    conversation_prompt_content: str | None = None,           # from prior PRD
) -> str:
```

In `parts` list construction:

After Layer 3B (emotional state machine / resistance level block), insert:

**If `last_mb_context` is set:**
```
LAYER 3B-CONT - PRIOR TURN REGISTER
In your last response: tone was {tone}, length was {sentence_length}{", you interrupted" if interruption_type else ""}.
Maintain tonal continuity unless the rep's behavior explicitly warrants a shift.
```

**If `behavior_directives` is set:**
Insert the `behavior_directives.directive_text` as a new part after Layer 3B-CONT (or after Layer 3B if no prior context).

### 1e. Wire into the orchestrator's turn-processing flow

In the method that calls `PromptBuilder.build()` (after `RepTurnPlan` is computed but before the LLM call):

1. Call `compute_behavior_directives(emotion_before=plan.emotion_before, emotion_after=plan.emotion_after, behavioral_signals=plan.behavioral_signals, active_objections=plan.active_objections)`
2. Pass the result as `behavior_directives=directives` to `PromptBuilder.build()`
3. Pass `last_mb_context=context.last_mb_plan` to `PromptBuilder.build()`

---

## Task 2: Wire Plan Back to Context in ws.py

**File:** `backend/app/voice/ws.py`

After the call to `micro_behavior_engine.apply_to_response()` returns the `MicroBehaviorPlan`, update the orchestrator context:

```python
orchestrator.update_last_mb_plan(session_id, plan)
```

Add `update_last_mb_plan(session_id: str, plan: MicroBehaviorPlan)` to `ConversationOrchestrator`:

```python
def update_last_mb_plan(self, session_id: str, plan: MicroBehaviorPlan) -> None:
    context = self._contexts.get(session_id)
    if context is None:
        return
    context.last_mb_plan = {
        "tone": plan.tone,
        "sentence_length": plan.sentence_length,
        "interruption_type": plan.interruption_type,
        "behaviors": plan.behaviors,
        "realism_score": plan.realism_score,
    }
```

---

## Task 3: Store Directives in Session State Event

**File:** `backend/app/voice/ws.py` or wherever `server.session.state` events are emitted

When emitting the `server.session.state` event after a rep turn is processed, include:

```json
{
  "behavior_directives": {
    "tone": "...",
    "sentence_length": "...",
    "interruption_mode": false
  }
}
```

This makes replay/debug tooling able to show exactly what constraints the LLM was operating under each turn.

---

## Task 4: Tests

**File:** `backend/tests/test_microbehavior_prompt_integration.py`

Test:

1. `compute_behavior_directives()` returns correct `tone` and `sentence_length` for each emotion state (spot-check neutral, skeptical, annoyed, hostile, curious, interested).

2. `compute_behavior_directives()` sets `interruption_mode=True` when `emotion_after in {"annoyed", "hostile"}` and `"ignores_objection"` is in `behavioral_signals`.

3. `compute_behavior_directives()` sets `interruption_mode=False` when signals are neutral.

4. `PromptBuilder.build()` with `behavior_directives` set includes `"LAYER 3C - BEHAVIORAL DIRECTIVES"` in the output.

5. `PromptBuilder.build()` with `last_mb_context` set includes `"LAYER 3B-CONT"` in the output.

6. `PromptBuilder.build()` with neither set does not include either new block (backward compat).

7. `update_last_mb_plan()` correctly updates the context's `last_mb_plan` dict.

All unit tests — no DB, no LLM calls, no WebSocket needed.

---

## Acceptance Criteria

- [ ] `compute_behavior_directives()` exists and produces correct output for all 6 emotion states
- [ ] `PromptBuilder.build()` output contains Layer 3C when directives are provided
- [ ] `PromptBuilder.build()` output is unchanged when `behavior_directives=None` (backward compat)
- [ ] `last_mb_plan` is set on context after each AI turn via `update_last_mb_plan()`
- [ ] `PromptBuilder.build()` references prior turn register when `last_mb_context` is set
- [ ] All new tests pass, no existing tests broken

---

## Reference Files

- `backend/app/services/micro_behavior_engine.py` — `TONE_BY_TRANSITION`, `DEFAULT_TONE_BY_EMOTION`, `SENTENCE_LENGTH_BY_EMOTION`, `_should_interrupt()` contain the exact logic to mirror
- `backend/app/services/conversation_orchestrator.py` — `PromptBuilder`, `ConversationContext`, `RepTurnPlan`, existing layer construction
- `backend/app/voice/ws.py` — where `apply_to_response()` is called and where `server.session.state` events are emitted
