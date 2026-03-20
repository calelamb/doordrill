# Codex Investigation + Fix: STT Pipeline Reliability

## What The User Is Experiencing

During live drills:
1. The homeowner says "What?" repeatedly even when the rep clearly spoke
2. Short but valid rep responses ("Yeah", "Right", "Exactly") get swallowed entirely
3. Transcription feels delayed or drops out mid-drill
4. The homeowner occasionally responds to something irrelevant, then the rep cuts it off

All symptoms trace back to the STT pipeline. This document tells you exactly where to look, what the bugs are, and how to fix them. Read every file listed under **Files to Read** before touching anything.

---

## Files to Read First

- `backend/app/services/provider_clients.py` — DeepgramSttClient, `_stream_utterance`, `consume_results`
- `backend/app/voice/ws.py` — `run_stt`, `_is_transcript_valid`, `MIN_TRANSCRIPT_WORD_COUNT`, `CLARIFICATION_RESPONSES`, the main event loop
- `backend/app/services/transcript_normalization_service.py` — `PHONETIC_CORRECTION_TABLE`, `_closest_token_match`, `DEFAULT_FUZZY_MATCH_THRESHOLD`

---

## Bug 1 — CRITICAL: speech_final regression causes ~1200ms phantom wait on every turn

**File:** `backend/app/services/provider_clients.py`
**Function:** `_stream_utterance` → `consume_results`

### What the code currently does

A recent fix changed `consume_results` to only `break` when Deepgram sends `speech_final: true`, so that multi-window long utterances get fully accumulated. This was the right idea for the long-utterance truncation problem, but it introduced a regression:

When `_stream_utterance` sends `{"type": "Finalize"}` to Deepgram, Deepgram forces the current utterance to finalize and responds with `Results { is_final: true }`. **Deepgram does NOT reliably set `speech_final: true` in response to an explicit `Finalize` command.** `speech_final` is set by Deepgram's internal VAD, which may or may not agree that speech has ended.

So after `Finalize` is sent, the current code:
1. Receives `Results { is_final: true, speech_final: false, transcript: "Yeah" }` → appends to segments, does NOT break
2. Waits for `speech_final: true` which never arrives
3. Finally receives `UtteranceEnd` after `utterance_end_ms = 1200ms` of silence
4. Breaks — 1200ms late

This adds **1200ms of unnecessary wait to every single turn.** For short responses ("Yeah", "Sure", "Right"), the delay is the full 1200ms. This is why the rep feels like their responses aren't being picked up — by the time the transcript arrives the conversation has stalled.

### The fix

Track whether `Finalize` has been sent within `_stream_utterance`. Pass that signal into `consume_results` so that once `Finalize` is confirmed sent, we break on `is_final: true` (any window) rather than waiting for `speech_final`.

The reason we can safely break on `is_final` after `Finalize` is sent: **we are the ones who ended the utterance.** There is no more audio coming. Multi-window accumulation is only needed for in-progress speech where Deepgram sends multiple `is_final` windows before `speech_final`. After `Finalize`, Deepgram may send one or two more `is_final` windows to drain its buffer — accumulate all of them, then break when no new `is_final` arrives within a short window (300ms), OR break immediately on the first `is_final` after `Finalize` if `speech_final` is also false and nothing is pending.

**Recommended implementation:**

Use a `finalize_sent` asyncio.Event inside `_stream_utterance`. Set it immediately after `await state.ws.send(json.dumps({"type": "Finalize"}))`. In `consume_results`, after accumulating each `is_final` window, check: if `finalize_sent.is_set()` and there are final segments already, set a short drain timeout (200ms). If the next recv() times out at 200ms and `finalize_sent` is set, break with whatever segments we have.

Concretely:
```python
finalize_sent = asyncio.Event()

async def consume_results() -> None:
    nonlocal latest_partial, final_segments, confidences
    while True:
        # Use a shorter timeout once we've sent Finalize — no more audio is coming
        recv_timeout = 0.2 if (finalize_sent.is_set() and final_segments) else self.timeout_seconds
        try:
            raw_message = await asyncio.wait_for(state.ws.recv(), timeout=recv_timeout)
        except TimeoutError:
            break  # If finalize is sent and we have segments, this is correct termination
        ...
        if is_final_window or speech_final:
            final_segments.append(transcript)
            confidences.append(confidence)
            _emit_handler(payload, "on_final", transcript, True)
            if speech_final:
                break  # Definitive end of speech
            # Otherwise continue draining — may be more windows before Finalize response
        ...

# In the send block:
async with state.lock:
    for idx in range(0, len(audio_bytes), 8192):
        await state.ws.send(audio_bytes[idx : idx + 8192])
    await state.ws.send(json.dumps({"type": "Finalize"}))
    finalize_sent.set()   # ← signal consume_results to use short timeout
await consume_results()
```

**Acceptance criteria:** On a 1-word response ("Yeah"), the STT returns within 300ms of the audio being sent. On a 20-word response, the full transcript is captured without truncation.

---

## Bug 2 — Single-word valid responses trigger clarification

**File:** `backend/app/voice/ws.py`
**Line:** `MIN_TRANSCRIPT_WORD_COUNT = 2`

### Problem

`_is_transcript_valid` returns `False` for any transcript with fewer than 2 words. This blocks single-word D2D responses like "Yeah", "Yes", "Right", "No", "Okay", "Sure", "Exactly", "Absolutely" from reaching the LLM. Instead, the homeowner says "What?" and the rep has to repeat themselves.

These 1-word responses are valid and contextually meaningful in D2D conversation. The 2-word minimum was designed to block truly empty or garbage transcripts, but it's too aggressive.

### The fix

Lower `MIN_TRANSCRIPT_WORD_COUNT` from `2` to `1`. Then compensate by adding a **content filter** that blocks single-word transcripts that are pure noise or filler artifacts, not real words:

```python
MIN_TRANSCRIPT_WORD_COUNT = 1

# Words that are valid Deepgram outputs but not meaningful rep speech
_NOISE_ONLY_TRANSCRIPTS: frozenset[str] = frozenset({
    "um", "uh", "mm", "hmm", "hm", "ah", "oh", "eh",
    "the", "a", "an",  # single articles — never a standalone rep utterance
})

def _is_transcript_valid(transcript: str) -> bool:
    if not transcript or not transcript.strip():
        return False
    words = TRANSCRIPT_WORD_RE.findall(transcript)
    if len(words) == 0:
        return False
    if len(words) == 1 and words[0].lower() in _NOISE_ONLY_TRANSCRIPTS:
        return False
    return True
```

**Acceptance criteria:** "Yeah", "Yes", "Exactly", "No" all pass `_is_transcript_valid`. "Um", "Uh", "Mm" still fail.

---

## Bug 3 — Clarification response "What?" sounds hostile and fires in a loop

**File:** `backend/app/voice/ws.py`
**Line:** `CLARIFICATION_RESPONSES`

### Problem

```python
CLARIFICATION_RESPONSES = [
    "Sorry, what was that?",
    "What?",
    "I didn't catch that.",
    "Hmm?",
    "Come again?",
]
```

"What?" is a valid realistic homeowner response to truly unintelligible speech, but when it fires back-to-back (Bug 1 causing two consecutive drops), the rep hears "What? ... What?" which feels hostile and broken, not human.

Additionally, the clarification response is picked **randomly** with no memory of what was just said. If clarification fires twice in a row, the homeowner can say "What?" twice, which no human would do.

### The fix

1. Remove `"What?"` from the pool — too blunt and indistinguishable from a software error
2. Add a state variable `_consecutive_clarification_count` in the main session loop. If clarification fires a second time in a row without a valid rep turn in between, pick from a **recovery sub-pool** that sounds more like a human:

```python
CLARIFICATION_RESPONSES = [
    "Sorry, I didn't catch that.",
    "Hmm, didn't quite get that.",
    "Could you say that again?",
    "Come again?",
    "Say that again?",
]

CLARIFICATION_RECOVERY_RESPONSES = [
    "Sorry, I'm having trouble hearing you.",
    "I'm not catching you — can you speak up?",
    "Hold on, I'm not hearing you well.",
]
```

Track `consecutive_clarification_count` as an `int` in the session loop (reset to 0 on any valid `rep_text`). If `consecutive_clarification_count >= 2`, draw from `CLARIFICATION_RECOVERY_RESPONSES` instead.

**Acceptance criteria:** No back-to-back "What?" responses. After two consecutive clarifications, the homeowner uses a recovery phrase.

---

## Bug 4 — Fuzzy term matcher may corrupt common short words

**File:** `backend/app/services/transcript_normalization_service.py`
**Function:** `_closest_token_match`

### Problem

`_apply_fuzzy_term_corrections` runs on every token in the transcript using `SequenceMatcher` with a threshold of 0.8. The canonical term list includes domain words (pest control, Orkin, Aptive, etc.) but also general words added from org config, scenario persona, and active objections.

Any common 4+ letter word that is 80% similar to a canonical term will be silently replaced. For example: "sure" might match "service" at 0.67 — too low to trigger, but the threshold for org-specific terms is lowered to 0.75. If "sure" ends up close to any org-specific single-token term, it could be corrupted.

More importantly, this fuzzy match runs on every single token in every transcript even when no pest control vocabulary is present. For a rep saying "I was just at your neighbor's house helping them out with their yard" — every token is being compared against the full canonical term list on every call.

### The fix

1. Add a minimum token length check — only apply fuzzy matching to tokens of length >= 5 (currently 4). This prevents "yes", "the", "got" from being candidates.

2. Add a maximum Levenshtein distance guard — a ratio of 0.8 between a 4-letter token and a 6-letter canonical term represents only 1 character difference, which is too loose. Instead require `ratio >= 0.85` for tokens shorter than 6 characters.

3. Log every applied correction at DEBUG level so it's possible to see when a real word is being incorrectly rewritten.

```python
# In _closest_token_match, tighten the token length gate
if len(lowered) < 5:  # was < 4
    return None

# And tighten threshold for short tokens
threshold = (
    ORG_SPECIFIC_FUZZY_MATCH_THRESHOLD
    if normalized in org_specific_terms
    else DEFAULT_FUZZY_MATCH_THRESHOLD
)
if len(lowered) < 6:
    threshold = max(threshold, 0.85)  # short tokens need tighter match
```

**Acceptance criteria:** "yeah", "sure", "okay", "just", "right", "got" do not get rewritten by the fuzzy matcher.

---

## Bug 5 — No STT debug logging makes it impossible to diagnose missed transcripts

**File:** `backend/app/services/provider_clients.py`
**File:** `backend/app/voice/ws.py`

### Problem

When a transcript comes back empty or very short, there is no logging showing what Deepgram actually returned. It's impossible to tell from logs whether:
- Deepgram returned a confident empty result (rep was silent)
- Deepgram returned a low-confidence partial that wasn't captured
- The audio was sent incorrectly
- The consume_results loop timed out before any result

### The fix

In `_stream_utterance`, log at INFO level after `consume_results` completes:
```python
logger.info(
    "deepgram_utterance_result",
    extra={
        "session_id": session_id,
        "final_segment_count": len(final_segments),
        "transcript": " ".join(final_segments).strip() or latest_partial or "(empty)",
        "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "finalize_sent": finalize_sent.is_set(),
        "audio_bytes": len(audio_bytes),
    },
)
```

In `ws.py`, log after `_is_transcript_valid` fails:
```python
logger.info(
    "transcript_blocked_too_short",
    extra={
        "session_id": session_id,
        "raw": transcript_result.raw_text,
        "normalized": rep_text,
        "word_count": len(TRANSCRIPT_WORD_RE.findall(rep_text)),
        "confidence": stt_result.confidence,
    },
)
```

**Acceptance criteria:** Every STT call produces a `deepgram_utterance_result` log entry. Every clarification trigger produces a `transcript_blocked_too_short` log entry.

---

## Bug 6 — Low-confidence transcripts reach the LLM and cause bad responses

**File:** `backend/app/voice/ws.py`
**Location:** After `transcript_normalizer.normalize(...)`, before `orchestrator.prepare_rep_turn(...)`

### Problem

There is no confidence gate. If Deepgram transcribes "I was just at your neighbor's house" as "I was just at your neighbor's mouse" with 0.35 confidence, that garbled text goes straight to the LLM and the homeowner responds to something nonsensical.

### The fix

After normalization, add a confidence check. If confidence is below a threshold AND the transcript is short (< 6 words), treat it as invalid and trigger clarification:

```python
LOW_CONFIDENCE_THRESHOLD = 0.45
LOW_CONFIDENCE_MAX_WORDS = 5

# After normalize(), before prepare_rep_turn():
if (
    stt_result.confidence < LOW_CONFIDENCE_THRESHOLD
    and len(TRANSCRIPT_WORD_RE.findall(rep_text)) <= LOW_CONFIDENCE_MAX_WORDS
    and stt_result.source == "deepgram"  # don't gate mock/hint-based results
):
    logger.info(
        "transcript_blocked_low_confidence",
        extra={
            "session_id": session_id,
            "raw": transcript_result.raw_text,
            "confidence": stt_result.confidence,
            "word_count": len(TRANSCRIPT_WORD_RE.findall(rep_text)),
        },
    )
    # Treat as invalid — same clarification path as too-short transcripts
    ...trigger clarification flow...
    continue
```

Do NOT apply the confidence gate to longer transcripts (>= 6 words) — Deepgram's confidence can be deceptively low on longer utterances even when the transcript is accurate.

**Acceptance criteria:** A garbled 3-word low-confidence transcript triggers clarification instead of reaching the LLM.

---

## Implementation Order

Fix in this exact order — each fix depends on or interacts with the previous:

1. **Bug 1** (speech_final → finalize_sent drain) — primary cause of "responses not picked up"
2. **Bug 5** (add STT logging) — do this alongside Bug 1 so you can verify it worked
3. **Bug 2** (MIN_TRANSCRIPT_WORD_COUNT → 1 + noise filter) — fixes single-word drops
4. **Bug 3** (clarification response pool + consecutive guard) — fixes "What? What?" loop
5. **Bug 4** (fuzzy match tightening) — fixes silent transcript corruption
6. **Bug 6** (confidence gate) — final quality gate after all the above

---

## Do Not Touch

- `speech_final` / `is_final_window` accumulation logic — preserve multi-window accumulation, only change the break condition (Bug 1 fix above)
- `SILENCE_FILLER_SECONDS = 9.0` and `DOOR_OPEN` stage guard — recently fixed, leave alone
- `endpointing_ms = 300` / `utterance_end_ms = 1200` — leave these values alone
- Any grading, scoring, analytics, or RAG service
- The latency PRD changes (`PRD_Latency_v1.md`) — those are a separate Codex run

---

## Tests to Write

- `test_consume_results_breaks_after_finalize_without_speech_final`: mock a Deepgram WebSocket that returns `is_final: true, speech_final: false` followed by 300ms silence. Assert the result arrives within 400ms and contains the transcript.
- `test_is_transcript_valid_single_valid_word`: assert "Yeah", "Yes", "Right", "No" all return True
- `test_is_transcript_valid_noise_words`: assert "um", "uh", "mm" return False
- `test_consecutive_clarification_uses_recovery_pool`: trigger clarification twice in a row, assert second response comes from `CLARIFICATION_RECOVERY_RESPONSES`
- `test_fuzzy_match_does_not_corrupt_common_words`: assert "yeah", "sure", "okay", "just" are not rewritten
