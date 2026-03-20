# PRD: STT Quality + Homeowner Response Smoothness — v1
**For:** Codex
**Owner:** Cale
**Status:** Ready for Implementation

---

## Background

Manual drill testing revealed two categories of failure:

1. **STT transcription failures**: The rep says "Hey how's it going" and the audio either arrives garbled, gets cut off mid-utterance, or fails to transcribe accurately. When this happens, the homeowner receives an empty or nonsensical transcript and the LLM is left with nothing to respond to.

2. **Homeowner LLM fallback bleed**: When the transcript is missing or the LLM prompt is over-constrained, the model produces out-of-character fallback phrases like _"I'm not sure what else to say right now"_ — text that no real homeowner would ever say. This is a meta-confusion signal from the LLM leaking through as dialogue.

These two problems compound each other: bad STT → empty transcript → confused LLM → fallback phrase → broken immersion.

---

## Audit Findings

### A: Deepgram `keywords` Parameter Wrong for nova-3

**File:** `app/services/provider_clients.py` → `_listen_url()`

The code sends `params["keywords"] = ",".join(vocabulary_hints[:12])`. The `keywords` parameter is **deprecated in nova-3**. Nova-3 uses `keyterm` for vocabulary boosting. Sending `keywords` to nova-3 silently does nothing — the domain terms (pest control, Orkin, bimonthly, EcoShield) get zero boost.

### B: Endpointing Set Too Aggressively (75ms)

**File:** `app/services/provider_clients.py` → `_listen_url()`

`"endpointing": str(int(payload.get("endpointing_ms") or 75))` — 75ms is the minimum Deepgram allows. At 75ms, any natural pause in speech (drawing breath, trailing off, searching for words) triggers an early finalization. A rep saying "Hey... how's it going?" with a natural hesitation gets cut at "Hey" and the rest is either lost or sent as a second utterance that the backend isn't expecting.

### C: `utterance_end_ms` Too Short (350ms)

**File:** `app/services/provider_clients.py` → `_listen_url()`

`utterance_end_ms: 350` — this is the silence window after which Deepgram sends `UtteranceEnd`. 350ms means Deepgram considers the utterance done after 350ms of silence. Natural conversational pauses between sentences exceed 350ms. The rep is getting cut off mid-thought.

### D: No `language` Parameter

Nova-3 performs better with `language: en-US` explicitly set. Without it, Deepgram auto-detects, which adds latency and occasionally guesses wrong, especially for domain-specific vocabulary.

### E: PHONETIC_CORRECTION_TABLE Missing Key Terms

**File:** `app/services/transcript_normalization_service.py`

Current table covers Orkin, pest control, aerosol, ant, rodent, inspection, exterminator. Missing:
- "apt of" / "apt iv" → "Aptive"
- "eco shield" / "echo shield" / "echo shelled" → "EcoShield"
- "bi monthly" / "by monthly" → "bimonthly"
- "terminix" STT variants → "Terminix" (sometimes comes through as "terminus" or "termini x")
- "de webbing" / "the webbing" → "dewebbing"
- "per imeter" → "perimeter"
- "some" / "sum" when following a number → number passthrough (minor)

### F: LLM Fallback Phrases Not Blocked in Layer 4

**File:** `app/services/conversation_orchestrator.py` → Layer 4 anti-pattern guards

The current Layer 4 guards: aggression, off-topic, coaching requests, unrealistic claims. There is no guard against the LLM producing meta-confusion phrases. When the LLM doesn't know what to do — because the transcript is empty, the prompt is over-constrained, or two instructions conflict — it outputs phrases like:
- "I'm not sure what else to say right now."
- "I don't really know how to respond to that."
- "Could you clarify what you mean?"
- "I'm not quite sure what you're asking."

These are AI assistant defaults bleeding through the persona. They need to be explicitly prohibited.

### G: Empty / Sub-Threshold Transcript Not Guarded Before LLM Call

**File:** `app/voice/ws.py`

If Deepgram returns an empty transcript or a transcript shorter than 2 words, the orchestrator is still called and the LLM still runs. The LLM generates a response to nothing — which is where the fallback phrase comes from. There is no minimum transcript length check before forwarding to the LLM.

### H: Vocabulary Hints Capped at 12 Terms with Wrong Param

**File:** `app/services/provider_clients.py` → `_listen_url()`

Vocabulary hints are limited to 12 and sent as the deprecated `keywords` param. Nova-3 accepts up to 100 `keyterm` entries. With only 12 terms and the wrong param name, domain vocabulary boosting is completely non-functional.

---

## Feature Specs

---

### S-01: Fix Deepgram Parameter — `keywords` → `keyterm`, Raise Cap to 100

**File:** `app/services/provider_clients.py` → `_listen_url()`

**What to Change:**

```python
# BEFORE
if vocabulary_hints:
    params["keywords"] = ",".join(vocabulary_hints[:12])

# AFTER
if vocabulary_hints:
    for term in vocabulary_hints[:100]:
        params.setdefault("keyterm", []).append(term)
    # Deepgram keyterm is sent as repeated query params, not comma-joined
    # Use urllib.parse.urlencode with doseq=True
```

Update `_listen_url()` to build the URL using `urlencode(params, doseq=True)` and pass `keyterm` as a list so each term becomes its own `keyterm=...` query parameter (Deepgram's required format).

Add `language` param:
```python
params["language"] = "en-US"
```

**Acceptance Criteria:**
- `_listen_url()` output contains `keyterm=` entries not `keywords=`
- `language=en-US` present in URL
- Up to 100 vocabulary hint terms included
- URL still parses as a valid websocket URL

---

### S-02: Fix Endpointing and Utterance End Defaults

**File:** `app/services/provider_clients.py` → `_listen_url()`
**File:** `app/voice/ws.py` → wherever `endpointing_ms` and `utterance_end_ms` are set in payloads

**What to Change:**

```python
# BEFORE
"endpointing": str(int(payload.get("endpointing_ms") or 75)),
"utterance_end_ms": str(int(payload.get("utterance_end_ms") or 350)),

# AFTER
"endpointing": str(int(payload.get("endpointing_ms") or 300)),
"utterance_end_ms": str(int(payload.get("utterance_end_ms") or 1200)),
```

Also add:
```python
"no_delay": "true",   # Emit partials immediately rather than buffering
```

**Reasoning:**
- 300ms endpointing: gives reps time for natural mid-sentence pauses without early cutoff
- 1200ms utterance_end: a full 1.2 seconds of silence means the rep is truly done speaking
- `no_delay`: reduces partial transcript latency so the UI feels more responsive

**Acceptance Criteria:**
- Default endpointing is 300ms, overridable via payload
- Default utterance_end_ms is 1200ms, overridable via payload
- `no_delay=true` in the URL

---

### S-03: Expand PHONETIC_CORRECTION_TABLE

**File:** `app/services/transcript_normalization_service.py`

**What to Add:**

```python
PHONETIC_CORRECTION_TABLE: dict[str, str] = {
    # ... existing entries ...

    # Competitor names
    "apt of": "Aptive",
    "apt iv": "Aptive",
    "aptiv": "Aptive",
    "app tive": "Aptive",
    "terminus": "Terminix",
    "termini x": "Terminix",
    "termini": "Terminix",

    # Company name
    "eco shield": "EcoShield",
    "echo shield": "EcoShield",
    "echo shelled": "EcoShield",
    "echo shields": "EcoShield",

    # Service terms
    "bi monthly": "bimonthly",
    "by monthly": "bimonthly",
    "buy monthly": "bimonthly",
    "de webbing": "dewebbing",
    "the webbing": "dewebbing",
    "per imeter": "perimeter",
    "peer imeter": "perimeter",
    "start up fee": "startup fee",
    "start-up fee": "startup fee",
    "per imeter treatment": "perimeter treatment",
    "cobwebs": "cobwebs",
    "cob webs": "cobwebs",
}
```

**Acceptance Criteria:**
- `test_transcript_normalization_service.py` has parametrized tests covering all new entries
- "apt iv" → "Aptive", "echo shield" → "EcoShield", "bi monthly" → "bimonthly"

---

### S-04: Block LLM Meta-Confusion Phrases in Layer 4

**File:** `app/services/conversation_orchestrator.py` → `layer_four_lines` in `build_prompt()`

**What to Add:**

Add a hard prohibition to the Layer 4 anti-pattern block:

```python
layer_four_lines.extend([
    # ... existing guards ...
    "NEVER say phrases like 'I'm not sure what else to say', 'I don't know how to respond to that', "
    "'Could you clarify', or any phrase that sounds like an AI admitting confusion. "
    "If you are confused by the rep's words, respond as any real homeowner would: "
    "'What was that?' / 'I didn't catch that.' / 'What are you selling?' — not a meta-commentary.",
])
```

**Why This Is Necessary:**
These phrases are the LLM's default confusion output leaking through the persona. They are immediately immersion-breaking. The fix is not to improve the prompt enough that the LLM never gets confused — the fix is to explicitly close the escape hatch.

**Acceptance Criteria:**
- Layer 4 block contains an explicit prohibition on confusion meta-phrases
- The prohibition includes positive alternatives ("What was that?", "What are you selling?")

---

### S-05: Empty Transcript Guard Before LLM Call

**File:** `app/voice/ws.py`

When Deepgram returns an empty string or a transcript shorter than 2 meaningful words, the LLM should not be called. Instead the pipeline should either:
- Stay silent (if transcript is truly empty)
- Send a "didn't catch that" homeowner line (if transcript is very short/garbled)

**What to Build:**

Add a check after transcript normalization, before the orchestrator call:

```python
MIN_TRANSCRIPT_WORD_COUNT = 2

def _is_transcript_valid(transcript: str) -> bool:
    """Return True if transcript has enough content to warrant an LLM response."""
    if not transcript or not transcript.strip():
        return False
    word_count = len(transcript.strip().split())
    return word_count >= MIN_TRANSCRIPT_WORD_COUNT

# In the main utterance processing path:
if not _is_transcript_valid(normalized_transcript):
    logger.info(
        "Transcript too short to process, skipping LLM call",
        extra={"raw": raw_transcript, "normalized": normalized_transcript, "session_id": session_id}
    )
    # Emit a natural "didn't catch that" response without calling LLM
    await _emit_clarification_response(session_id)
    return
```

`_emit_clarification_response()` should pick from a small fixed pool of realistic homeowner responses:
```python
CLARIFICATION_RESPONSES = [
    "Sorry, what was that?",
    "What?",
    "I didn't catch that.",
    "Hmm?",
]
```
Pick one randomly and send it through TTS as if it were a normal homeowner turn. Do NOT call the LLM.

**Acceptance Criteria:**
- Transcript of "" or single-word utterance does not trigger LLM call
- A clarification response is emitted through TTS instead
- `test_voice_ws.py` (or equivalent) has a test: empty transcript → clarification response, no LLM call

---

### S-06: Add `disfluencies: false` to Deepgram Params

**File:** `app/services/provider_clients.py` → `_listen_url()`

Add:
```python
params["disfluencies"] = "false"
```

This suppresses Deepgram from transcribing filler words ("um", "uh", "like") as content. Currently if the rep says "Um, hey how's it going?" Deepgram includes the "um" in the transcript. This pollutes the LLM's view of the rep's speech and can confuse signal detection in `ConversationTurnAnalyzer`.

**Acceptance Criteria:**
- `disfluencies=false` present in Deepgram URL params

---

## Implementation Priority

| # | Feature | Impact | Effort | Do First? |
|---|---|---|---|---|
| S-04 | Block meta-confusion phrases | High — immediate immersion fix | 10 min | YES |
| S-05 | Empty transcript guard | High — prevents empty→LLM calls | 30 min | YES |
| S-01 | `keyterm` param fix + language | High — vocabulary boosting broken | 20 min | YES |
| S-02 | Endpointing defaults | High — stops mid-utterance cutoff | 10 min | YES |
| S-03 | PHONETIC_CORRECTION_TABLE | Medium — improves D2D term recognition | 20 min | YES |
| S-06 | `disfluencies: false` | Low — cleaner transcripts | 5 min | YES |

All six are small. Codex should implement all of them in one session.

---

## Files to Modify

| File | Changes |
|---|---|
| `app/services/provider_clients.py` | S-01: keyterm, language, doseq URL encoding; S-02: endpointing/utterance_end defaults; S-06: disfluencies |
| `app/services/transcript_normalization_service.py` | S-03: expand PHONETIC_CORRECTION_TABLE |
| `app/services/conversation_orchestrator.py` | S-04: Layer 4 meta-confusion phrase prohibition |
| `app/voice/ws.py` | S-05: empty transcript guard + clarification response pool |

## Files to Create / Modify for Tests

| File | Changes |
|---|---|
| `tests/test_transcript_normalization_service.py` | Add parametrized tests for new phonetic entries |
| `tests/test_provider_clients.py` | Assert `keyterm` in URL, `keywords` absent, `language=en-US` present, endpointing=300 |

---

## Do NOT Change

- `DEEPGRAM_MODEL` setting (stays `nova-3`)
- `smart_format`, `punctuate`, `interim_results` params — these are correct
- The retry/reconnect logic in `_stream_utterance()`
- `TranscriptNormalizationResult` schema
- Existing phonetic entries in `PHONETIC_CORRECTION_TABLE` (only add, do not remove)
