# PRD: Voice Pipeline Latency Reduction
**Version:** 1.0
**Target:** Codex
**Status:** Ready for implementation

---

## Background

DoorDrill's voice loop is: Deepgram STT → Turn Analysis → OpenAI/Anthropic LLM → ElevenLabs TTS → audio bytes over WebSocket. The pipeline is architecturally sound but has several compounding inefficiencies that together push end-to-end latency (VAD end → first audio byte) above what feels natural in a real conversation. A human-speed reply is < 800ms. Based on current instrumentation and a review of the code, we are likely running 1.2–1.8s on typical turns.

The latency record already exists (`TurnLatencyRecord`) and tracks five timestamps: `vad_end_ts`, `stt_final_ts`, `analysis_complete_ts`, `llm_first_token_ts`, `first_audio_byte_ts`. These are emitted as `phase_latency_breakdown` in `server.session.state`. This PRD uses that breakdown as the measurement baseline.

---

## Goals

- Reduce **total turn latency** (VAD end → first audio byte) from ~1.5s → < 900ms on typical 1–2 sentence homeowner turns
- Each phase should hit: STT ≤ 300ms | Analysis ≤ 50ms | LLM first token ≤ 450ms | TTS first chunk ≤ 150ms
- Zero regressions to transcription accuracy or homeowner response quality
- All improvements measurable via existing `TurnLatencyRecord`

---

## Implementation Priority

| ID | Title | Phase | Effort | Expected Win |
|----|-------|-------|--------|-------------|
| L-01 | Remove per-chunk asyncio.sleep(0) in Deepgram send | STT | XS | ~50ms |
| L-02 | ElevenLabs output_chunk_length_schedule | TTS | XS | ~80ms first chunk |
| L-03 | ElevenLabs apply_text_normalization=false | TTS | XS | ~30ms |
| L-04 | Bump ElevenLabs optimize_streaming_latency to 4 | TTS | XS | ~40ms |
| L-05 | Remove OpenAI stream_options include_usage | LLM | XS | ~10ms |
| L-06 | Trim conversation history to 3 exchanges (6 messages) | LLM | XS | ~40ms prompt build |
| L-07 | Fire TTS without waiting for first_tts_audio_started | LLM→TTS | S | ~200ms |
| L-08 | Widen sentence-split to also fire on comma-pause | LLM→TTS | S | ~100ms perceived |
| L-09 | Extend TurnLatencyRecord with two new timestamps | Measurement | S | Observability |
| L-10 | Real-time Deepgram audio streaming | STT | L | ~400ms STT |

Implement in the order listed. L-01 through L-06 are one-line or two-line changes. L-07 and L-08 touch `ws.py` sentence pipeline. L-09 is additive. L-10 is the largest and requires a mobile coordination plan — implement last.

---

## Requirements

### L-01 — Remove per-chunk asyncio.sleep(0) in Deepgram send

**File:** `backend/app/services/provider_clients.py`
**Function:** `_stream_utterance` → the send loop

**Current code:**
```python
for idx in range(0, len(audio_bytes), 8192):
    await state.ws.send(audio_bytes[idx : idx + 8192])
    await asyncio.sleep(0)  # ← yields event loop 20+ times for a 5s utterance
await state.ws.send(json.dumps({"type": "Finalize"}))
```

**Problem:** For a 5-second utterance at 16kHz mono 16-bit PCM ≈ 160KB, this produces ~20 event-loop yields before the audio is fully sent to Deepgram. Each yield costs ~1–5ms of scheduling overhead. More importantly, Deepgram cannot begin processing the audio until it receives a meaningful amount — fragmenting sends this way delays the moment Deepgram first sees the audio.

**Fix:** Send all chunks in a tight loop without yielding, then yield once after Finalize:
```python
async with state.lock:
    for idx in range(0, len(audio_bytes), 8192):
        await state.ws.send(audio_bytes[idx : idx + 8192])
    await state.ws.send(json.dumps({"type": "Finalize"}))
await asyncio.sleep(0)  # single yield after full send
```

**Acceptance criteria:** `stt_ms` in `TurnLatencyRecord` decreases by at least 30ms on a 3-second test utterance.

---

### L-02 — ElevenLabs output_chunk_length_schedule

**File:** `backend/app/services/provider_clients.py`
**Function:** `ElevenLabsTtsClient.stream_audio`

**Current payload:**
```python
payload = {
    "text": cleaned_text,
    "model_id": self.model_id,
    "optimize_streaming_latency": 3,
    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
}
```

**Problem:** ElevenLabs flushes audio chunks based on internal defaults. The first chunk can be delayed 200–400ms because ElevenLabs waits to accumulate enough audio before flushing. `output_chunk_length_schedule` controls the byte sizes for the first N chunks — starting small forces faster first-flush.

**Fix:** Add `output_chunk_length_schedule` to the payload:
```python
payload = {
    "text": cleaned_text,
    "model_id": self.model_id,
    "optimize_streaming_latency": 4,   # also bumped per L-04
    "output_chunk_length_schedule": [50, 120, 200, 250, 300],
    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    "apply_text_normalization": "none",  # per L-03
}
```

**Acceptance criteria:** `tts_first_audio_ms` in `TurnLatencyRecord` decreases by at least 60ms.

---

### L-03 — ElevenLabs apply_text_normalization=false

**File:** `backend/app/services/provider_clients.py`
**Function:** `ElevenLabsTtsClient.stream_audio`

**Problem:** ElevenLabs runs a text normalization pass (expanding abbreviations, numbers, etc.) on every request. Our homeowner responses are already natural prose — no numbers to expand, no abbreviations. This pass adds unnecessary latency.

**Fix:** Add `"apply_text_normalization": "none"` to the ElevenLabs payload (combined into the change in L-02 above).

---

### L-04 — Bump ElevenLabs optimize_streaming_latency to 4

**File:** `backend/app/services/provider_clients.py`
**Function:** `ElevenLabsTtsClient.stream_audio`

**Problem:** Currently `optimize_streaming_latency: 3`. Level 4 is ElevenLabs' maximum latency optimization mode. At level 3→4, quality is reduced very slightly but latency drops ~30–50ms. For a roleplay homeowner where natural rhythm matters more than studio quality, this tradeoff is worth it.

**Fix:** Change `"optimize_streaming_latency": 3` → `"optimize_streaming_latency": 4` (combined into L-02 change).

---

### L-05 — Remove OpenAI stream_options include_usage

**File:** `backend/app/services/provider_clients.py`
**Function:** `OpenAiLlmClient.stream_reply`

**Current:**
```python
payload = {
    ...
    "stream_options": {"include_usage": True},
    ...
}
```

**Problem:** `include_usage: true` forces OpenAI to append a final data chunk containing token counts after `[DONE]`. This adds a round-trip at the end of the stream and can delay the server-side detection of stream completion by 10–30ms.

**Fix:** Remove the `stream_options` key entirely from the payload dict. We don't use the usage data anywhere in the hot path.

**Acceptance criteria:** No functional change; `llm_first_token_ms` should be unaffected but stream completion is faster.

---

### L-06 — Trim conversation history to 3 exchanges (6 messages)

**File:** `backend/app/services/provider_clients.py`
**Class:** `_TaskConversationHistoryMixin._remember_exchange`

**Current:**
```python
if len(history) > 16:
    del history[:-16]
```

**Problem:** 16 messages = 8 full exchanges. For homeowner turns averaging ~15 tokens each, this adds up to ~240 tokens of context prepended to every LLM call. More tokens = longer prompt processing time. A homeowner roleplay only needs the last 3 exchanges (6 messages) to stay contextually coherent — anything earlier is scene-setting that's already captured in the system prompt.

**Fix:**
```python
if len(history) > 6:
    del history[:-6]
```

**Acceptance criteria:** `llm_first_token_ms` decreases on turn 5+ (where history is non-trivial). No observable homeowner coherence degradation in a 10-turn test drill.

---

### L-07 — Fire TTS without waiting for first_tts_audio_started

**File:** `backend/app/voice/ws.py`
**Function:** `stream_ai_response` → `process_sentence` call site

**Current code:**
```python
tts_tasks.append(_track_tts_task(asyncio.create_task(stream_tts_for_plan(plan))))
if len(tts_tasks) == 1 and not first_tts_audio_started.is_set():
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(first_tts_audio_started.wait(), timeout=0.2)
```

**Problem:** After creating the first TTS task, the code synchronously waits up to 200ms for the first audio byte before processing the next LLM token. The intent was to ensure the first sentence starts playing before the second is queued, to avoid audio overlap. But this wait stalls the LLM streaming loop and can delay the second sentence's TTS task creation by 200ms — adding directly to end-to-end latency.

The `tts_emit_lock` in `stream_tts_for_plan` already serializes audio emission correctly. We don't need the wait — tasks are queued and run sequentially via the lock.

**Fix:** Remove the `await asyncio.wait_for(first_tts_audio_started.wait(), ...)` block entirely. Keep `first_tts_audio_started.set()` in `stream_tts_for_plan` for logging purposes only.

```python
tts_tasks.append(_track_tts_task(asyncio.create_task(stream_tts_for_plan(plan))))
# Do not wait — tts_emit_lock already serializes emission; waiting stalls the LLM loop
```

**Acceptance criteria:** `tts_first_audio_ms` unchanged or improved. No audio overlap observed. `llm_first_token_ms` → `first_sentence_ts` gap decreases.

---

### L-08 — Widen sentence-split to fire TTS on comma-pause for longer chunks

**File:** `backend/app/voice/ws.py`
**Function:** `stream_ai_response` → sentence buffer loop

**Current code:**
```python
sentence_buffer += str(chunk)
while True:
    match = re.search(r"[.?!](?:\s|$)", sentence_buffer)
    if match is None:
        break
    sentence = sentence_buffer[:match.end()].strip()
    sentence_buffer = sentence_buffer[match.end():].lstrip()
    await process_sentence(sentence)
```

**Problem:** If the LLM responds with "Got it, yeah, we actually don't have pest problems right now" — the whole thing is one sentence that only fires TTS after the complete token stream. The user hears nothing until the LLM finishes. Breaking on comma when the buffer has ≥ 8 words fires TTS much earlier for the first chunk ("Got it, yeah,"), so audio starts while the rest is still generating.

**Fix:** After the `.?!` split, add a secondary comma-split when the buffer is long enough:
```python
sentence_buffer += str(chunk)
while True:
    # Primary split: sentence-ending punctuation
    match = re.search(r"[.?!](?:\s|$)", sentence_buffer)
    if match is not None:
        sentence = sentence_buffer[:match.end()].strip()
        sentence_buffer = sentence_buffer[match.end():].lstrip()
        await process_sentence(sentence)
        continue
    # Secondary split: comma-pause when buffer has accumulated enough words
    # (avoids micro-chops on "Well, I..." style openings)
    comma_match = re.search(r",\s+", sentence_buffer)
    if comma_match is not None and len(sentence_buffer[:comma_match.start()].split()) >= 7:
        sentence = sentence_buffer[:comma_match.end()].strip().rstrip(",")
        sentence_buffer = sentence_buffer[comma_match.end():].lstrip()
        await process_sentence(sentence)
        continue
    break
```

**Acceptance criteria:** For a homeowner response that is a single sentence of ≥ 10 words, first audio byte arrives before the LLM stream completes. No perceptible audio choppiness in a 10-turn drill.

---

### L-09 — Extend TurnLatencyRecord with audio send and TTS request timestamps

**Files:**
- `backend/app/utils/latency.py`
- `backend/app/services/provider_clients.py`
- `backend/app/voice/ws.py`

**Problem:** The current `TurnLatencyRecord` doesn't measure two of the most useful sub-phases:
1. How long it takes to send the audio blob to Deepgram (`audio_send_ms`) — this reveals whether L-01 actually helped and whether connection reuse is working
2. How long from ElevenLabs request to first chunk (`tts_request_to_first_chunk_ms`) — this reveals whether L-02/L-03/L-04 are having an effect

**Fix — latency.py:** Add two new optional fields to `TurnLatencyRecord` and `TurnBudgetMetrics`:
```python
audio_send_end_ts: Optional[float] = None  # after last audio byte sent to Deepgram
tts_request_ts: Optional[float] = None     # when ElevenLabs HTTP request is initiated
```

Add computed properties to `to_budget_metrics()`:
```python
# audio_send_ms: time from vad_end_ts to audio_send_end_ts
# tts_request_ms: time from tts_request_ts to first_audio_byte_ts
```

**Fix — provider_clients.py:** In `_stream_utterance`, record `audio_send_end_ts` immediately after the `Finalize` send. Pass it back via the `SttTranscript` or a callback. In `ElevenLabsTtsClient.stream_audio`, accept an optional `on_request_start` callback and call it before `client.stream("POST", ...)`.

**Fix — ws.py:** Wire the callbacks through `run_stt` payload and `stream_tts_for_plan`. Set `turn_latency.audio_send_end_ts` and `turn_latency.tts_request_ts` accordingly. Include both in the `phase_latency_breakdown` emitted on `server.session.state`.

**Acceptance criteria:** `phase_latency_breakdown` now includes `audio_send_ms` and `tts_request_ms` fields. Both are non-null on real Deepgram + ElevenLabs turns.

---

### L-10 — Real-time Deepgram audio streaming (streaming architecture upgrade)

**Files:**
- `backend/app/voice/ws.py`
- `backend/app/services/provider_clients.py`
- Mobile app audio recording logic

**Problem (largest latency source):** Currently the entire utterance is buffered on the mobile, sent as one base64 blob in `client.audio.chunk`, and then replayed to Deepgram as a batch. This means:
- Deepgram doesn't see any audio until after the rep stops speaking
- For a 4-second utterance, Deepgram starts processing ~4 seconds after speech began
- Deepgram then takes an additional ~300–500ms to finalize the transcript

In a true streaming setup, Deepgram begins processing from the very first 100ms of audio. By the time the rep stops speaking, Deepgram has already processed most of the utterance and only needs to finalize the tail — cutting STT latency to near zero.

**Architecture change:**

*Mobile side:*
During recording, emit `client.audio.stream` events every ~100ms with the raw PCM chunk (NOT waiting for recording to end). Continue emitting `client.vad.state {speaking: false}` when VAD detects end of speech. Remove `client.audio.chunk` (the batch event) or keep it as a fallback for older clients.

*Server side — ws.py:*
Add handling for `client.audio.stream` events in `receive_loop`. On each `client.audio.stream` event, decode the base64 audio chunk and call a new `providers.stt.stream_audio_chunk(session_id, chunk_bytes)` method that pipes it to the open Deepgram WebSocket immediately (no lock needed — just `await state.ws.send(chunk_bytes)`).

When `client.vad.state {speaking: false}` fires, call `providers.stt.trigger_finalization()` (which sends `{"type": "Finalize"}`) and simultaneously start `consume_results()` to await the final transcript.

The `consume_results()` loop already exists and will work correctly — it now just runs *while* the user is still potentially speaking the last word, rather than after the whole utterance.

*Server side — provider_clients.py:*
Add `DeepgramSttClient.stream_audio_chunk(session_id: str, chunk: bytes) -> None` — a thin wrapper that gets the session state and calls `await state.ws.send(chunk)` without the lock (sends are thread/task safe on the websockets library). Add `DeepgramSttClient.await_finalized_transcript(session_id: str, payload: dict) -> SttTranscript` that calls `trigger_finalization()` then `consume_results()`.

**SUPPORTED_CLIENT_EVENTS update:** Add `"client.audio.stream"` to the set.

**Backward compatibility:** If the mobile sends `client.audio.chunk` (old batch event) instead of `client.audio.stream`, fall back to the existing `run_stt` path. Both paths should coexist during transition.

**Acceptance criteria:**
- `stt_ms` in `TurnLatencyRecord` (vad_end → stt_final) decreases from ~500ms → < 100ms on a 3-second utterance
- No regression in transcription accuracy (run a 10-turn drill comparing transcripts)
- Backward compatibility: old `client.audio.chunk` path still works

---

## Measurement Plan

Before and after each change, log the `phase_latency_breakdown` from 10 consecutive turns of a test drill. Compare:

| Metric | Baseline target | Post-all-fixes target |
|--------|----------------|-----------------------|
| `stt_ms` | ≤ 600ms | ≤ 100ms (with L-10) or ≤ 400ms (without L-10) |
| `analysis_ms` | ≤ 100ms | ≤ 50ms |
| `llm_first_token_ms` | ≤ 600ms | ≤ 450ms |
| `tts_first_audio_ms` | ≤ 300ms | ≤ 150ms |
| `total_turn_ms` | ≤ 1800ms | ≤ 900ms |

The `phase_latency_breakdown` is already emitted in `server.session.state` events on every turn. No new endpoints are needed for measurement — just inspect the WebSocket event log.

---

## Files to Read Before Implementing

- `backend/app/utils/latency.py` — TurnLatencyRecord and TurnBudgetMetrics
- `backend/app/services/provider_clients.py` — DeepgramSttClient, OpenAiLlmClient, ElevenLabsTtsClient
- `backend/app/voice/ws.py` — run_stt, stream_ai_response, process_sentence, maybe_emit_silence_filler
- `backend/app/core/config.py` — provider model and timeout settings

## Do Not Change

- `speech_final` vs `is_final` logic in `consume_results` — recently fixed, critical correctness
- `SILENCE_FILLER_SECONDS = 9.0` and `DOOR_OPEN` stage guard — recently fixed
- `endpointing_ms = 300` / `utterance_end_ms = 1200` — tuned STT values from previous PRD
- Any grading, scoring, or analytics service — out of scope

---

## Test Protocol

After completing L-01 through L-09:
1. Run a 10-turn drill with a mix of short (2–5 word) and long (10–20 word) rep utterances
2. Capture the `phase_latency_breakdown` from each `server.session.state` event
3. Confirm `total_turn_ms` median is ≤ 900ms
4. Confirm no double homeowner turns (silence filler regression check)
5. Confirm no truncated transcripts on 15+ word utterances (speech_final regression check)
