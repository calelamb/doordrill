# PRD: Voice Pipeline Latency Optimization

**Status:** Ready for implementation
**Scope:** Backend — `ws.py`, `conversation_orchestrator.py`, `document_retrieval_service.py`
**SLOs:** P50 < 900ms first audio byte after rep stops speaking; P95 < 1400ms; barge-in interrupt < 150ms

---

## Background

DoorDrill's real-time voice loop is: Deepgram STT → Claude 3.5 Sonnet LLM (streamed) → ElevenLabs TTS (sentence-level streaming). The critical latency metric is **time from end-of-rep-speech to first audio byte from the AI homeowner**.

Sentence-level TTS streaming is already implemented — `process_sentence()` fires a TTS task per sentence as the LLM streams, so the homeowner begins speaking before the full LLM response is done. That is the biggest win and it's in.

What remains are several smaller but measurable wins totaling an estimated 150–400ms off the hot path:

| Item | Estimated saving | Complexity |
|------|-----------------|------------|
| VAD-triggered STT finalization | 80–200ms | Low |
| Parallel RAG context retrieval | 30–80ms at session start | Trivial |
| Deferred post-turn DB commit | 15–40ms per turn | Low |
| System prompt token cap | 10–30ms LLM prefill | Medium |
| Adaptive flush interval | 5–15ms | Low |

None of these require architectural changes. All are safe, incremental, and independently deployable.

---

## Non-Goals

- Do not change the TTS provider or LLM provider.
- Do not restructure the WebSocket message protocol.
- Do not change the sentence boundary detection regex.
- Do not remove any of the new prompt layers added by previous PRDs (3B-CONT, 3C, Layer 5). The token cap task measures and enforces limits; it does not remove content.

---

## Task 1: VAD-Triggered STT Finalization

**File:** `backend/app/voice/ws.py`

### Problem

Currently, `run_stt()` calls `providers.stt.finalize_utterance(payload)` after the STT provider emits a final transcript. Deepgram's default VAD waits for a configurable silence window (typically 500ms–1000ms) after the last speech segment before marking the utterance final. This silence gap is dead time — the rep has stopped talking, but the system is waiting.

The WebSocket already receives `client.vad.state` events with `speaking: false` when the rep stops talking. This signal arrives faster than Deepgram's utterance-end decision.

### Fix

In `receive_loop()`, when a `client.vad.state` event arrives with `speaking: false`:

1. Set a flag `_vad_end_pending = True` on the session state.
2. Start a short debounce timer (`VAD_FINALIZE_DEBOUNCE_MS = 80`ms). If VAD state returns to `speaking: true` within this window, cancel the timer (barge-in, not end of utterance).
3. If the debounce elapses without reversal, call `stt_provider.trigger_finalization()` — a new method on the STT provider interface that signals "end of utterance now" rather than waiting for the silence window.

### STT Provider Interface

**File:** `backend/app/providers/stt_provider.py` (or wherever the Deepgram wrapper lives — check `backend/app/providers/`)

Add an optional method to the provider interface:

```python
async def trigger_finalization(self) -> None:
    """
    Signal to the STT provider that the utterance is complete.
    Called when VAD detects end-of-speech, allowing the provider
    to finalize transcript without waiting for its own silence window.
    For Deepgram: send a UtteranceEnd message via the live client.
    """
```

For Deepgram's live client, sending a `UtteranceEnd` message causes the server to flush and finalize the current utterance immediately. The Deepgram Python SDK exposes `live_client.send(UtteranceEnd(...))` for this.

### New Constants

```python
VAD_FINALIZE_DEBOUNCE_MS: int = 80   # wait this long after VAD end before triggering finalization
```

Add alongside the existing `SILENCE_FILLER_SECONDS`, `MAX_RUNTIME_PAUSE_MS` constants at the top of `ws.py`.

### Failure Mode

If `trigger_finalization()` is not supported by a provider (e.g., not Deepgram), the method is a no-op. The existing silence-based finalization remains as the fallback — no behavior change for unsupported providers.

---

## Task 2: Parallel RAG Context Retrieval at Session Start

**File:** `backend/app/voice/ws.py`, lines ~181–222

### Problem

At session start, `ws.py` loads RAG context with two sequential `asyncio.run_in_executor` calls:

```python
# Current (sequential — approximately 30-80ms wasted)
pricing_chunks = await loop.run_in_executor(None, retrieve_pricing, ...)
competitor_chunks = await loop.run_in_executor(None, retrieve_competitors, ...)
```

These queries hit the same database / pgvector index independently and have no data dependency on each other.

### Fix

Replace with `asyncio.gather`:

```python
pricing_chunks, competitor_chunks = await asyncio.gather(
    loop.run_in_executor(None, retrieve_pricing, ...),
    loop.run_in_executor(None, retrieve_competitors, ...),
)
```

This is a one-line change. Both queries run concurrently and the total wait time is `max(t_pricing, t_competitor)` instead of `t_pricing + t_competitor`.

### Also: Cache Warm-Up at Session Bind

If `document_retrieval_service.py` uses any in-process cache (LRU or similar) for embeddings or results, ensure the session bind step (`bind_session_context()` in the orchestrator) pre-warms it by calling `retrieve_for_topic()` for common topics during session initialization, not the first rep turn. This prevents a cold-cache penalty on turn 1.

If no cache exists currently, add a simple `functools.lru_cache` keyed on `(org_id, topic, k)` with a 5-minute TTL (use `cachetools.TTLCache`) to avoid re-embedding the same query within a session.

---

## Task 3: Deferred Post-Turn DB Commit

**File:** `backend/app/voice/ws.py`, lines ~1043–1046

### Problem

After committing the AI turn, `ws.py` does:

```python
db.commit()
db.refresh(ai_turn)
```

This is synchronous I/O on the hot path between the LLM response finishing and the next rep turn being ready to process. The `db.refresh()` re-fetches the row from Postgres, which is unnecessary if no columns were server-generated after the insert (or if the generated values aren't needed immediately).

### Fix

**Option A (preferred): Remove `db.refresh()`**

Audit whether any code downstream in the same request uses fields that are server-generated (e.g., `created_at` set by DB default, auto-increment IDs). If `ai_turn.id` was set in Python before the commit (UUID assigned in application layer), `db.refresh()` is a no-op functionally and can be removed.

**Option B: Move commit to background task**

If the commit must happen synchronously, wrap it in `asyncio.get_event_loop().run_in_executor(None, db.commit)` so it doesn't block the event loop. The session is already streaming audio at this point; the commit is bookkeeping.

**Do not defer the commit if downstream code in the same request reads the committed turn ID from the DB.** Check for any query that runs after line 1046 within the same request scope before choosing Option B.

### Also: Batch Turn Writes

If `TurnEnrichmentService` (called in post-processing) re-reads and re-writes the same `SessionTurn` row, ensure it uses a single `UPDATE` statement rather than `SELECT` + modify + `UPDATE`. This is a post-session concern, not real-time, but reduces overall DB load.

---

## Task 4: System Prompt Token Audit and Cap

**File:** `backend/app/services/conversation_orchestrator.py`

### Problem

`PromptBuilder.build()` now assembles up to 8 layers:
- Layer 1: Immersion baseline
- Layer 2: Persona
- Layer 3: Stage instruction
- Layer 3B: Emotion/resistance state machine
- Layer 3B-CONT: Prior turn register (NEW)
- Layer 3C: Behavioral directives (NEW)
- Layer 4: Anti-patterns
- Layer 4B: Edge cases
- Layer 5: Prompt override from DB (NEW)

Plus conversation history. The total prompt length directly affects LLM time-to-first-token (prefill cost scales with prompt length).

### Fix

#### 4a. Add a `measure_prompt_tokens()` utility

```python
def measure_prompt_tokens(text: str) -> int:
    """Approximate token count using tiktoken cl100k_base encoding."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))
```

Add this as a module-level function in `conversation_orchestrator.py`. Use `tiktoken` (already a common dependency; add to `requirements.txt` if absent).

#### 4b. Add system prompt budget constants

At the top of `conversation_orchestrator.py`, add:

```python
SYSTEM_PROMPT_SOFT_LIMIT_TOKENS = 1200   # log warning if exceeded
SYSTEM_PROMPT_HARD_LIMIT_TOKENS = 1600   # truncate Layer 4B if exceeded
```

#### 4c. Add `_enforce_prompt_budget()` to `PromptBuilder`

After `parts` list is assembled but before `"\n\n".join(parts)`:

```python
def _enforce_prompt_budget(self, parts: list[str]) -> list[str]:
    """
    Measures total token count of all prompt parts.
    Logs a warning if soft limit is exceeded.
    Truncates Layer 4B (edge cases) if hard limit would be exceeded —
    this is the lowest-priority layer and is safe to trim.
    """
    total = sum(measure_prompt_tokens(p) for p in parts)
    if total > SYSTEM_PROMPT_HARD_LIMIT_TOKENS:
        logger.warning(
            "system_prompt_over_hard_limit",
            token_count=total,
            parts_count=len(parts),
        )
        # Layer 4B is the last "optional detail" layer — trim it first
        parts = [p for p in parts if "LAYER 4B" not in p]
        total = sum(measure_prompt_tokens(p) for p in parts)
    elif total > SYSTEM_PROMPT_SOFT_LIMIT_TOKENS:
        logger.info("system_prompt_over_soft_limit", token_count=total)
    return parts
```

Call `_enforce_prompt_budget(parts)` inside `build()` before joining.

#### 4d. Emit token count in session state event

When emitting `server.session.state`, include:

```json
{
  "system_prompt_token_count": 847
}
```

This lets the debug dashboard show prompt size over time and catch regressions.

---

## Task 5: Adaptive `maybe_flush()` Interval

**File:** `backend/app/voice/ws.py`

### Problem

`maybe_flush()` runs on a fixed `ws_flush_interval_ms = 350ms` schedule to flush the ledger/event queue to the client. During periods of high activity (AI is streaming audio), 350ms is fine. During silence gaps (between rep utterance end and first AI audio), 350ms may delay delivery of lightweight state events (e.g., `server.session.state` carrying the new emotional state for the client UI).

### Fix

Dynamically adjust the flush interval based on session phase:

```python
FLUSH_INTERVAL_ACTIVE_MS = 200   # during AI speech or post-VAD window
FLUSH_INTERVAL_IDLE_MS = 400     # during rep speech or silence
```

In `maybe_flush()`, check the current session phase:

```python
interval = (
    FLUSH_INTERVAL_ACTIVE_MS
    if session_state.phase in {"ai_speaking", "post_vad"}
    else FLUSH_INTERVAL_IDLE_MS
)
```

This is a micro-optimization (5–15ms) but also makes the client UI feel more responsive during the AI's speaking phase, since state events arrive ~150ms sooner on average.

---

## Task 6: Barge-In Interrupt Latency Audit

**File:** `backend/app/voice/ws.py`

### Problem

Barge-in (rep speaking over the AI) requires:
1. VAD detects `speaking: true`
2. `set_interrupt()` is called
3. Audio stops streaming to client
4. STT begins capturing rep's new utterance

The current interrupt path is already wired in `receive_loop()`. This task is an **audit**, not a rewrite.

### What to check and fix if broken

#### 6a. Verify interrupt cancels TTS tasks immediately

When `set_interrupt()` is called, ensure all in-flight `asyncio.Task` instances created by `process_sentence()` (i.e., `stream_tts_for_plan(plan)` tasks) are cancelled immediately via `task.cancel()`, not just flagged.

Check: is there a list/set of active TTS tasks maintained on the session? If so, confirm `set_interrupt()` iterates and cancels them. If not, add one:

```python
# On session state
active_tts_tasks: set[asyncio.Task] = set()

# In process_sentence():
task = asyncio.create_task(stream_tts_for_plan(plan))
session_state.active_tts_tasks.add(task)
task.add_done_callback(session_state.active_tts_tasks.discard)

# In set_interrupt():
for task in list(session_state.active_tts_tasks):
    task.cancel()
session_state.active_tts_tasks.clear()
```

#### 6b. Verify audio flush on interrupt

When TTS tasks are cancelled, the ElevenLabs stream may have already sent partial audio packets to the client. Confirm that a `server.audio.interrupt` message (or equivalent) is sent to the client immediately, so the client-side audio player clears its buffer. Without this, the client plays buffered audio for 200–500ms after the interrupt arrives.

#### 6c. Measure barge-in round-trip

Add timing instrumentation:

```python
# When VAD speaking=true arrives:
logger.info("barge_in_detected", ts=time.monotonic())

# When first rep STT partial arrives after barge-in:
logger.info("barge_in_stt_first_partial", ts=time.monotonic(), latency_ms=...)
```

Log the delta. Target is < 150ms. If consistently above, the bottleneck is likely the ElevenLabs connection close round-trip, not our code.

---

## Task 7: Latency Instrumentation

**File:** `backend/app/voice/ws.py` and a new `backend/app/utils/latency.py`

### Problem

Without structured latency logging, it's impossible to measure whether any of the above tasks actually improved P50/P95. We need per-turn timing so we can compute these percentiles from logs.

### Fix

#### 7a. Create `backend/app/utils/latency.py`

```python
import time
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class TurnLatencyRecord:
    session_id: str
    turn_index: int

    # Timestamps (monotonic seconds)
    vad_end_ts: Optional[float] = None          # VAD speaking=false
    stt_final_ts: Optional[float] = None         # STT utterance finalized
    llm_first_token_ts: Optional[float] = None   # First token from LLM
    first_sentence_ts: Optional[float] = None    # First sentence boundary hit
    tts_task_created_ts: Optional[float] = None  # First TTS asyncio.Task created
    first_audio_byte_ts: Optional[float] = None  # First audio packet sent to client

    def log_summary(self, logger) -> None:
        if self.vad_end_ts and self.first_audio_byte_ts:
            total_ms = (self.first_audio_byte_ts - self.vad_end_ts) * 1000
            stt_ms = ((self.stt_final_ts or 0) - (self.vad_end_ts or 0)) * 1000
            llm_ms = ((self.llm_first_token_ts or 0) - (self.stt_final_ts or 0)) * 1000
            tts_ms = ((self.first_audio_byte_ts or 0) - (self.tts_task_created_ts or 0)) * 1000
            logger.info(
                "turn_latency",
                session_id=self.session_id,
                turn_index=self.turn_index,
                total_ms=round(total_ms),
                stt_ms=round(stt_ms),
                llm_ms=round(llm_ms),
                tts_ms=round(tts_ms),
            )
```

#### 7b. Wire timing checkpoints in `ws.py`

At each stage transition, set the corresponding timestamp on a `TurnLatencyRecord` instance maintained on the session. Call `record.log_summary()` when first audio byte is sent.

These are `time.monotonic()` calls — zero overhead. The structured log output enables a simple query on the log aggregator (Datadog, CloudWatch, etc.) to compute P50/P95 distributions.

---

## Implementation Order

These tasks are independent. Recommended order for Codex:

1. **Task 2** (parallel RAG) — trivial, zero risk, immediate gain
2. **Task 1** (VAD finalization) — highest latency impact
3. **Task 3** (deferred DB commit) — requires Option A/B audit first
4. **Task 7** (instrumentation) — should go in alongside Task 1 so you can measure it
5. **Task 4** (token cap) — measurement first, then enforce
6. **Task 6** (barge-in audit) — audit + fix if needed
7. **Task 5** (adaptive flush) — lowest priority

---

## Acceptance Criteria

- [ ] RAG context retrieval at session start uses `asyncio.gather`
- [ ] VAD end-of-speech triggers STT finalization after `VAD_FINALIZE_DEBOUNCE_MS` with no regression on barge-in
- [ ] `db.refresh()` removed or deferred; no downstream breakage
- [ ] `PromptBuilder.build()` enforces `SYSTEM_PROMPT_HARD_LIMIT_TOKENS`; logs warning at soft limit
- [ ] `server.session.state` events include `system_prompt_token_count`
- [ ] `TurnLatencyRecord` logs `turn_latency` structured events with `total_ms`, `stt_ms`, `llm_ms`, `tts_ms`
- [ ] Barge-in audit confirms TTS tasks are cancelled (not just flagged) and client receives interrupt message
- [ ] No new test failures; existing WS test suite passes

---

## Reference Files

- `backend/app/voice/ws.py` — all tasks touch this file
- `backend/app/providers/` — Task 1 (STT provider `trigger_finalization`)
- `backend/app/services/conversation_orchestrator.py` — Task 4 (token cap in `PromptBuilder`)
- `backend/app/services/document_retrieval_service.py` — Task 2 (RAG parallelism)
- `backend/app/utils/` — Task 7 (new `latency.py` utility)
