# Codex Implementation Prompt — STT Quality + Homeowner Smoothness

Read `PRD_STT_Homeowner_Smoothness_v1.md` in full before writing any code.

## What You're Fixing

Two compounding problems discovered in manual drill testing:

1. **STT cuts off the rep mid-utterance** due to overly aggressive endpointing (75ms), sends vocabulary hints using a deprecated Deepgram parameter (`keywords` instead of `keyterm`), and lacks `language` and `disfluencies` settings.

2. **The homeowner LLM produces meta-confusion phrases** like "I'm not sure what else to say right now" — AI assistant defaults that bleed through when the transcript is empty or the prompt is conflicted. These are immersion-breaking and need to be explicitly blocked.

## Implementation Order

1. **S-04** (10 min) — Add meta-confusion phrase prohibition to Layer 4 in `conversation_orchestrator.py`. Quickest win.

2. **S-02** (10 min) — Fix endpointing (75ms → 300ms) and utterance_end_ms (350 → 1200) in `provider_clients.py`.

3. **S-06** (5 min) — Add `disfluencies=false` to Deepgram params.

4. **S-01** (20 min) — Replace `keywords` with `keyterm`, add `language=en-US`. Switch URL encoding to `urlencode(params, doseq=True)` so `keyterm` can be repeated.

5. **S-03** (20 min) — Expand `PHONETIC_CORRECTION_TABLE` with Aptive, EcoShield, bimonthly, dewebbing, Terminix variants.

6. **S-05** (30 min) — Add empty transcript guard in `ws.py`. If transcript < 2 words, skip LLM, emit a random clarification response via TTS.

## Critical Details

### S-01: keyterm URL encoding
Deepgram `keyterm` must be sent as repeated query params:
```
?keyterm=pest+control&keyterm=EcoShield&keyterm=Orkin
```
NOT as:
```
?keywords=pest+control,EcoShield,Orkin
```
Use `urllib.parse.urlencode(params, doseq=True)` where `params["keyterm"]` is a list.

### S-04: Exact wording for Layer 4 addition
Add inside `layer_four_lines.extend([...])`, AFTER the existing entries:
```
"NEVER produce meta-confusion phrases such as 'I'm not sure what else to say', "
"'I don't know how to respond to that', 'Could you clarify what you mean', or any "
"phrase that sounds like an AI expressing uncertainty about the roleplay. "
"If the rep's words were unclear or too brief, respond as a real homeowner: "
"'What was that?' or 'Hmm?' or 'What are you selling?' — never break character."
```

### S-05: Clarification response pool
```python
import random
CLARIFICATION_RESPONSES = [
    "Sorry, what was that?",
    "What?",
    "I didn't catch that.",
    "Hmm?",
    "Come again?",
]
```
Emit the chosen response through the existing TTS path (same way a normal homeowner turn is sent). Do NOT add a new session turn to the database — this is a passthrough audio response only.

### S-05: Minimum word count
`MIN_TRANSCRIPT_WORD_COUNT = 2` — a single word (like "hey" or "um") should trigger clarification. Two or more words should proceed normally.

## Tests Required

- `test_provider_clients.py`: assert `keyterm` in URL, `keywords` not in URL, `language=en-US` in URL, endpointing is 300, utterance_end_ms is 1200
- `test_transcript_normalization_service.py`: parametrized over new phonetic entries — at minimum: "apt iv" → "Aptive", "echo shield" → "EcoShield", "bi monthly" → "bimonthly", "terminus" → "Terminix"

## Files to Touch

- `backend/app/services/provider_clients.py` — S-01, S-02, S-06
- `backend/app/services/transcript_normalization_service.py` — S-03
- `backend/app/services/conversation_orchestrator.py` — S-04
- `backend/app/voice/ws.py` — S-05
