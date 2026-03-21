# Voice Realism & Comprehension Design Spec

**Date:** 2026-03-20
**Status:** Approved
**Goal:** Make the AI homeowner fully understand the rep and respond with natural, unscripted-feeling dialogue — fixing both STT accuracy (the ears) and response quality (the brain).

---

## Problem Statement

The AI homeowner has two compounding issues:

1. **STT accuracy:** Deepgram frequently misrecognizes domain-specific vocabulary (pest species, chemicals, company names, product names), feeding garbled input to the LLM.
2. **Generic responses:** Even with correct transcripts, the homeowner often gives canned, disconnected responses that don't engage with what the rep actually said. Rigid word caps (10/20/30), a "one sentence only" rule, and post-hoc micro-behavior text injection all contribute.

These are roughly 50/50 in frequency. Audio quality is fine — the issue is domain vocabulary, not environment noise.

## Approach

**Approach B: Smarter Ears + Smarter Brain.** Fix the input pipeline with a transcript repair layer and better STT provider. Fix the output quality by overhauling the prompt architecture, moving micro-behavior intent into the LLM prompt, and adding a response quality gate. Budget: up to 500ms additional latency is acceptable for meaningfully better realism.

---

## Section 1: Transcript Repair Layer

**Where it fits:** New step between `run_stt()` and `ConversationOrchestrator.prepare_rep_turn()` in `ws.py`.

### How it works

1. **Domain vocabulary registry** — A new module (`backend/app/services/transcript_repair_service.py`) holds a pest control vocabulary: species (German cockroach, brown recluse, subterranean termite), chemicals (bifenthrin, fipronil), product names, common company names, and sales jargon. Structured as a dictionary mapping common misrecognitions to correct terms (e.g., "German watches" -> "German cockroaches", "by fen thin" -> "bifenthrin"). Loaded once at startup.

2. **Fast deterministic pass** — Before hitting any LLM, run a regex/fuzzy-match pass against the vocabulary. Catches obvious misrecognitions with zero latency cost. Uses `rapidfuzz` for edit-distance matching on individual tokens and bigrams. **Dependency:** Add `rapidfuzz` to `backend/pyproject.toml` (or `setup.cfg`) under `[project.dependencies]`.

3. **LLM repair pass (conditional)** — If fuzzy match confidence is low on any token OR the transcript contains unusual words not in the vocabulary, send the transcript + last 2 turns of conversation context to a fast model with a tight prompt: *"Fix domain-specific speech recognition errors in this pest control sales transcript. Only change words that are clearly misrecognized. Return the corrected transcript only."* Budget: ~200ms, max 100 tokens. Model selection: uses the existing `LLM_PROVIDER` setting but with a fast model override. Add `TRANSCRIPT_REPAIR_MODEL` to `config.py` (default: `claude-haiku-4-5-20251001` for Anthropic, `gpt-4o-mini` for OpenAI). This reuses the existing provider's API key — no separate credentials needed.

4. **Skip logic** — If the deterministic pass repairs everything with high confidence, skip the LLM call entirely. Most turns add 0ms; only ambiguous transcripts pay the 200ms cost.

**Integration:** The repaired transcript replaces the raw STT output before anything else sees it. The raw transcript is still logged for debugging.

---

## Section 2: Prompt Architecture Overhaul

### Remove hard constraints, add natural guidance

- Remove the "one sentence only" rule and the 10/20/30 word caps from `PromptBuilder.build()`.
- Remove `homeowner_token_budget()` as a hard LLM `max_tokens` parameter. Set a generous ceiling (80-100 tokens) and let the prompt guide length naturally.
- Replace with per-emotion length guidance baked into the prompt:

| Emotion | Guidance |
|---------|----------|
| hostile | "You want this over. A few sharp words, maybe a sentence." |
| annoyed | "Keep it short and impatient. One sentence, maybe two if you're making a point." |
| skeptical | "You're testing them. A pointed question or a short challenge." |
| neutral | "Polite but measured. A sentence or two." |
| curious | "You're engaging now. Ask a real question or share a thought." |
| interested | "You're warming up. You might think out loud for a couple sentences." |

### Move micro-behavior intent into the prompt

- Add a `delivery_direction` line to the prompt based on emotion/transition: *"Delivery: hesitant and guarded -- you might trail off or second-guess yourself mid-sentence."* or *"Delivery: direct and clipped -- no pleasantries."*
- The LLM produces text that naturally includes hesitations when appropriate, because it knows the emotional intent.
- The micro-behavior engine shifts to TTS metadata only (see Section 5).

### Add life details to persona (Layer 2 expansion)

`PersonaEnricher` gets new fields auto-generated per scenario:

- `at_home_reason`: "working from home", "day off", "retired", "stay-at-home parent"
- `last_salesperson_experience`: "had a solar guy last week who wouldn't leave", "never really gets solicitors"
- `specific_memory`: "neighbor Bob had termites last year and it cost him $3,000", "saw a roach in the garage last month"
- `current_mood_reason`: "in the middle of making lunch", "was about to leave for an errand"

These go into Layer 2. The LLM can reference them naturally: *"Look, my neighbor just dealt with this and it was a nightmare"* instead of generic *"I'm not interested."*

Generated deterministically from scenario difficulty + persona fields using template tables (no extra LLM call at session start). Example generation logic:

```python
# at_home_reason: keyed on household_type
AT_HOME_TEMPLATES = {
    "family with kids": ["stay-at-home parent", "working from home today"],
    "retired couple": ["retired, home most days"],
    "single homeowner": ["day off", "working from home"],
}

# specific_memory: keyed on pest_history + difficulty
MEMORY_TEMPLATES = [
    "neighbor {name} had {pest} last year and it cost around ${cost}",
    "saw a {pest} in the {room} {timeframe}",
    "read something online about {pest} in this area",
]
# {name}, {pest}, {room}, {cost}, {timeframe} filled from small random pools
# seeded by hash(scenario_id) for determinism
```

Each field has 8-12 templates per category. The combination of persona fields + scenario difficulty selects the template; `hash(scenario_id)` picks the specific fill values for determinism across sessions.

### Expand conversation history

- Increase rolling window from 12 to 24 turns in `_TaskConversationHistoryMixin`.
- Add a summary of turns that fall outside the window: a 2-3 sentence recap of what was discussed early in the conversation. Uses the same fast model as transcript repair (`TRANSCRIPT_REPAIR_MODEL` — Haiku/GPT-4o-mini). The summary is stored alongside the rolling window in the `WeakKeyDictionary` entry as a `context_summary: str` field.
- **Update frequency:** Summary is generated once when the window first shifts (after turn 24), then updated every 4 turns thereafter — not every turn. This limits the cost to ~1 extra LLM call per 4 turns in long drills. Most drills end before turn 24 and never trigger this.
- **Latency note:** The summary LLM call (~150-300ms) runs asynchronously after the current turn completes — it does NOT block the current response. The summary from the previous update is used for the current turn's context.

---

## Section 3: Response Quality Gate

### Problem it solves

Even with better transcripts and prompts, the LLM will occasionally produce a response that doesn't engage with what the rep actually said -- a generic "I'm not interested" when the rep just asked a specific question about their pest history.

### How it works

1. **Relevance check** — After the LLM finishes streaming but before TTS begins for the last segment, run a fast heuristic check: does the response reference or logically follow from the rep's last statement?
   - Extract key nouns/verbs from the rep's transcript (e.g., "inspection", "free", "next Tuesday")
   - Check if the homeowner's response engages with at least one, OR is a contextually appropriate deflection (e.g., "I need to go" is always valid for an annoyed/hostile homeowner)
   - Score: `engaged`, `deflection`, or `disconnected`

2. **Regeneration (rare)** — Only if scored `disconnected`, regenerate with an augmented prompt: *"The rep just said: '{rep_transcript}'. Your response MUST directly address what they said -- react to their specific words, not to a generic pitch."* Adds ~1-1.5 seconds but should trigger on less than 10% of turns.

3. **No double-regeneration** — If the second attempt is still disconnected, use it anyway. One retry max.

### Where it fits and timing details

The quality gate runs after the LLM stream completes and the full response text is known. Implementation detail for the sentence pipeline in `ws.py`:

- Sentences are TTS'd incrementally as the LLM streams. For most responses (1-2 sentences), TTS for the first sentence is already playing by the time the LLM finishes.
- The relevance check runs on the **complete response text** after the last sentence boundary is detected. This is a local heuristic — no LLM call, no latency added to the happy path.
- **If `disconnected`:** Cancel any TTS tasks that haven't started emitting audio yet. Regenerate the full response with the augmented prompt. All new TTS starts from scratch. The client will experience a pause after whatever audio already played — this is acceptable for a rare (~10%) path.
- **If the full response is a single sentence** and its TTS has already started playing: do NOT regenerate. The audio is already out. Accept it. The quality gate is most valuable for multi-sentence responses where later sentences drift off-topic.
- Does NOT block first audio in the happy path (`engaged` or `deflection` score).

---

## Section 4: STT Provider Strategy

### New approach

1. **Primary provider: AssemblyAI** — Better out-of-the-box accuracy for domain vocabulary, supports custom vocabulary/boost terms, real-time streaming via WebSocket. Add `AssemblyAiSttClient` alongside existing `DeepgramSttClient` in `provider_clients.py`, following the same interface (`finalize_utterance`, `end_session`, partial callback pattern).

2. **Configuration:** Add `STT_PROVIDER` setting to `config.py` (values: `deepgram`, `assemblyai`, `mock`). Default to `assemblyai`. Add `ASSEMBLYAI_API_KEY` env var. Existing provider resolution pattern in `ProviderSuite.from_settings()` handles this cleanly.

3. **Custom vocabulary at session bind:** When the session starts in `ws.py`, pass domain terms to the STT provider. AssemblyAI supports `word_boost` with up to 1000 terms. Load terms from:
   - A static pest control vocabulary file (`backend/app/data/vocab_pest_control.json`)
   - The scenario's company-specific terms (company name, product names from RAG chunks)
   - Happens once at session start, not per utterance

   **Interface change required:** `BaseSttClient.start_session` currently accepts only `session_id: str`. Update the base class signature to: `async def start_session(self, session_id: str, *, vocabulary: list[str] | None = None) -> None`. Update `DeepgramSttClient.start_session` to accept and pass vocabulary as Deepgram `keywords` (it already accepts a `payload` dict — normalize to the new interface). Update `MockSttClient` to accept and ignore the parameter. Update the call site in `ws.py` to pass vocabulary loaded from vocab file + scenario terms.

4. **Keep Deepgram as fallback:** If AssemblyAI fails or times out, fall back to Deepgram. The transcript repair layer from Section 1 still runs regardless of provider -- defense in depth.

5. **Latency expectation:** AssemblyAI real-time is comparable to Deepgram (~100-300ms for streaming partials). No latency regression expected.

**Not doing:** Whisper self-hosted. Higher accuracy but batch-only (no streaming), which would add 2-3 seconds waiting for the full utterance before transcription starts.

---

## Section 5: Micro-Behavior Engine Refactoring

### Current role (two concerns)
1. Transforms LLM text by injecting fillers, hesitations, and interruptions
2. Generates TTS metadata (pause timing, barge-in windows, tone labels)

### New role: TTS metadata only. No more text transforms.

### Changes in `micro_behavior_engine.py`

- `apply_to_response()` stops modifying `transformed_text`. The text from the LLM is the text that goes to TTS.
- `HESITATION_VARIANTS`, `FILLER_VARIANTS`, `INTERRUPTION_VARIANTS` -- no longer injected into text. These constants move into prompt guidance (Section 2) as examples the LLM can choose to use naturally.
- **Remove `_apply_sentence_length`** — this method currently truncates text (takes first sentence only for `short` length, truncates at first comma). It is a text modification and must be removed along with the filler/hesitation injection.
- Engine still computes and returns: `tone`, `sentence_length`, `pause_before_ms`, `pause_after_ms`, `allow_barge_in`, `segment_index/count`, `realism_score`. These drive TTS pacing and mobile player behavior.
- `MicroBehaviorPlan` and `MicroBehaviorSegment` dataclasses stay the same structurally, but `transformed_text` always equals input text.
- Segment splitting (sentence boundaries) stays in the engine.

### Changes in `ws.py`

- `build_behavior_plan()` still called, but output no longer diverges from LLM text.
- `process_sentence()` passes LLM text through unchanged. Plan metadata still drives `stream_tts_for_plan()` pause/barge-in behavior.

### Pause timing refinement

- Increase `MAX_RUNTIME_PAUSE_MS` from 60 to 300ms for natural conversational rhythm. This is the true ceiling — the engine's `_pause_before_ms` may compute values above 300ms (up to 420ms for hesitation-prefixed sentences), but those will be clamped to 300ms by `maybe_apply_pause` in `ws.py`.
- Hostile/annoyed: 0-50ms pauses (rapid, impatient)
- Neutral/skeptical: 100-200ms pauses (measured)
- Curious/interested: 150-300ms pauses (thoughtful)

### Net effect

The LLM owns all language choices (words, fillers, hesitations). The engine owns all delivery timing (pauses, segments, barge-in). Clean separation, no semantic mismatches.

---

## Section 6: Integration & Performance Budget

### End-to-end latency breakdown

| Step | Current | New | Delta |
|------|---------|-----|-------|
| STT (AssemblyAI streaming) | 100-500ms | 100-300ms | ~same |
| Transcript repair (deterministic) | N/A | 5-10ms | +10ms |
| Transcript repair (LLM, conditional) | N/A | 0-200ms | +0-200ms |
| LLM first token | 500-2000ms | 500-2000ms | same |
| LLM streaming + sentence split | 50-200ms | 50-200ms | same |
| Micro-behavior (metadata only) | 0-5ms | 0-5ms | same |
| TTS first chunk | 200-600ms | 200-600ms | same |
| Response quality gate | N/A | 0ms (parallel to TTS) | +0ms |
| Response quality regeneration (rare) | N/A | 0-1500ms (~10% of turns) | rare |

**Typical turn: ~2-4.5 seconds** (vs. current ~2-4 seconds). Within the 500ms budget. Regeneration is the only case that exceeds it, and it's rare.

### Files modified

| File | Change |
|------|--------|
| `backend/app/services/provider_clients.py` | Add `AssemblyAiSttClient` |
| `backend/app/core/config.py` | Add `STT_PROVIDER`, `ASSEMBLYAI_API_KEY`, `TRANSCRIPT_REPAIR_MODEL`, `TRANSCRIPT_REPAIR_ENABLED`, `RESPONSE_QUALITY_GATE_ENABLED` settings |
| `backend/app/voice/ws.py` | Insert transcript repair call, wire quality gate, update pause cap |
| `backend/app/services/conversation_orchestrator.py` | Overhaul `PromptBuilder.build()`, expand `PersonaEnricher`, update history window |
| `backend/app/services/micro_behavior_engine.py` | Remove text transforms, keep metadata-only role |
| `backend/app/services/transcript_repair_service.py` | **New file** -- domain vocab + fuzzy match + conditional LLM repair |
| `backend/app/data/vocab_pest_control.json` | **New file** -- pest control domain vocabulary |

### Files NOT modified

Mobile app, dashboard, grading service, database models, migrations. Entirely backend pipeline work -- the mobile app receives the same WebSocket events with the same schema, just better content.

### Feature flags

Individual features can be disabled without code changes for safe rollout:

| Flag | Default | Effect when `False` |
|------|---------|---------------------|
| `TRANSCRIPT_REPAIR_ENABLED` | `True` | Skips repair layer, raw STT goes to orchestrator |
| `RESPONSE_QUALITY_GATE_ENABLED` | `True` | Skips relevance check, no regeneration |

STT provider switching is already handled by `STT_PROVIDER` config. Prompt changes and micro-behavior refactoring have no toggle — they are structural improvements that go live together.

### Testing strategy

- Unit tests for `transcript_repair_service.py` with known misrecognition examples
- Unit tests for updated `PromptBuilder` -- verify prompts contain emotion-driven length guidance, delivery direction, life details
- Integration test: mock STT -> repair -> LLM -> verify response engages with rep input
- Existing `pytest` suite must still pass -- changes are additive/behavioral, not structural
