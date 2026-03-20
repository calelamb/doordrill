# Rep–AI interaction: accurate transcription and better AI audio

This roadmap narrows in on **what the homeowner “hears”** (STT quality) and **how the homeowner sounds and speaks** (OpenAI text + ElevenLabs voice). Garbage-in from STT drives nonsensical LLM replies; weak prompts or TTS settings make good text feel flat or robotic.

**Pipeline (where quality is won or lost):** mic → Deepgram → [`TranscriptNormalizationService`](../../backend/app/services/transcript_normalization_service.py) → [`ConversationOrchestrator`](../../backend/app/services/conversation_orchestrator.py) → [`OpenAiLlmClient.stream_reply`](../../backend/app/services/provider_clients.py) → micro-behavior → [`ElevenLabsTtsClient.stream_audio`](../../backend/app/services/provider_clients.py) → mobile player ([`backend/app/voice/ws.py`](../../backend/app/voice/ws.py)).

```mermaid
flowchart LR
  Rep[Rep speech]
  DG[Deepgram + keyterms]
  Norm[Normalize + hints]
  GPT[OpenAI homeowner]
  EL[ElevenLabs TTS]
  Ear[Rep hears homeowner]
  Rep --> DG --> Norm --> GPT --> EL --> Ear
```

---

## Tracking

### Transcription accuracy

- [ ] Log and review `deepgram_utterance_result` (raw vs final text, confidence) per session; sample failures where rep intent ≠ transcript
- [ ] Expand `keyword_hints` / org + scenario vocabulary feeding Deepgram `keyterm` (see [`_current_vocabulary_hints`](../../backend/app/voice/ws.py) → `transcript_normalizer.keyword_hints`)
- [ ] Tune `endpointing_ms` / `utterance_end_ms` and VAD debounce for **fewer clipped endings** vs **premature finalize** ([`_stt_turn_tuning`](../../backend/app/voice/ws.py), [`_listen_url`](../../backend/app/services/provider_clients.py))
- [ ] Review `LOW_CONFIDENCE_THRESHOLD` and short-transcript rules so bad STT triggers clarification instead of wrong homeowner replies ([`ws.py`](../../backend/app/voice/ws.py))
- [ ] Grow `PHONETIC_CORRECTION_TABLE` and domain lists from real mishears (pest brands, plan names, local place names)

### OpenAI (homeowner replies)

- [ ] Add explicit system guidance: respond to the **literal rep transcript**; if ambiguous, ask a short clarifying question (reduces “mouse vs house” derailment)
- [ ] A/B `temperature` and `max_tokens` (`homeowner_token_budget`) for coherence vs variety ([`OpenAiLlmClient`](../../backend/app/services/provider_clients.py), orchestrator)
- [ ] Align prompt layers with **active objections and stage** so replies reference what the rep actually addressed ([`conversation_orchestrator.py`](backend/app/services/conversation_orchestrator.py))
- [ ] When `LLM_PROVIDER=openai`, validate `OPENAI_MODEL` for instruction-following vs cost (measure bad-turn rate on fixed eval transcripts)

### ElevenLabs (how the homeowner sounds)

- [ ] Compare `eleven_flash_v2_5` vs higher-fidelity models for **natural prosody** on objections and interruptions; document latency vs quality tradeoff ([`config.py`](../../backend/app/core/config.py) `ELEVENLABS_MODEL_ID`)
- [ ] Tune `voice_settings.stability` / `similarity_boost` (currently `0.5` / `0.75` in [`ElevenLabsTtsClient`](../../backend/app/services/provider_clients.py)) per persona or emotion
- [ ] Audit micro-behavior **segment length and pauses** so TTS input reads like speech, not bullet points ([`micro_behavior_engine.py`](../../backend/app/services/micro_behavior_engine.py))

---

## 1. Transcribe the rep accurately (Deepgram + preprocessing)

### 1.1 Deepgram request shape (already in code)

[`DeepgramSttClient._listen_url`](../../backend/app/services/provider_clients.py) sets `model`, `smart_format`, `punctuate`, `interim_results`, `endpointing`, `utterance_end_ms`, `language`, `no_delay`, and optional repeated **`keyterm`** from `vocabulary_hints` (Nova 3).

**Accuracy levers:**

- **`keyterm` / vocabulary hints** — You already pass scenario-, org-, and objection-derived hints from [`_current_vocabulary_hints`](../../backend/app/voice/ws.py). Prioritize: competitor names, product names, local geography, objection phrases. Cap is 100 terms; rank by frequency and session relevance.
- **Endpointing vs truncation** — Aggressive VAD/finalize improves latency but can **cut off final words**. Tune `endpointing_ms`, `utterance_end_ms`, and VAD debounce together; measure WER or human spot-checks, not latency alone.
- **Audio upstream** — Wrong `encoding` / `sample_rate` / `mimetype` pairing historically caused empty or poor transcripts ([`PRODUCTION_CHECKLIST.md`](../ops/PRODUCTION_CHECKLIST.md)). Keep client metadata honest and consistent with [`_normalized_audio_params`](../../backend/app/services/provider_clients.py).

### 1.2 After Deepgram: normalization and gating

[`TranscriptNormalizationService`](../../backend/app/services/transcript_normalization_service.py) applies domain terms, phonetic fixes, and fuzzy corrections. That is often **cheaper than fighting the ASR** for recurring pest-industry mishears.

[`ws.py`](../../backend/app/voice/ws.py) can block low-confidence or too-short transcripts and play clarification lines instead of sending garbage to the LLM. Tuning thresholds is a direct accuracy lever: too strict → annoying “say again”; too loose → homeowner responds to nonsense.

### 1.3 Optional deeper passes (product decision)

Backend config includes Whisper-related settings (`WHISPER_*`) for cleanup paths—useful if you add a **second-pass** or **dispute** flow for grading or replay, less suited for the sub-second live turn unless async.

### 1.4 Diagnostics

Implement or standardize logging described in [`CODEX_PROMPT_STT_FLOW.md`](../../CODEX_PROMPT_STT_FLOW.md): correlate **raw Deepgram output**, **post-normalization text**, and **LLM reply** for failed drills.

---

## 2. Better homeowner *text* from OpenAI

The homeowner only “knows” what the rep said through the **transcript string** passed into `stream_reply`. Accuracy work in §1 pays off here.

**Prompting:**

- Instruct the model to **ground every turn in the latest user message** and to **ask a short clarification** when the transcript is vague or ungrammatical (common right after bad STT).
- Keep **emotion, stage, and active objections** in the system prompt ([`conversation_orchestrator.py`](../../backend/app/services/conversation_orchestrator.py)) so replies are consistent and challenging, not generic chatbot filler.

**API parameters** ([`OpenAiLlmClient`](../../backend/app/services/provider_clients.py)):

- **`temperature`** (currently `0.4`) — lower for more predictable objection handling; slightly higher for varied personas if rubric allows.
- **`max_tokens`** — tied to `homeowner_token_budget(stage)`; too low causes clipped answers; too high encourages rambling that sounds unnatural when spoken.

**Model choice:** Stronger models usually follow multi-constraint prompts (persona + stage + objection stack) more reliably; validate with fixed transcripts and blind manager ratings.

---

## 3. Better homeowner *audio* from ElevenLabs

TTS quality depends on **input text** (micro-behavior output), **voice ID**, **model_id**, and **voice_settings**.

[`ElevenLabsTtsClient`](../../backend/app/services/provider_clients.py) today uses:

- `model_id` from env (default `eleven_flash_v2_5` — latency-first),
- `optimize_streaming_latency: 3`,
- `voice_settings`: `stability` / `similarity_boost` fixed at `0.5` / `0.75`.

**Directions:**

- **Model** — Flash is fast; if reps report “robotic” homeowners, try a higher-quality model for the same text and compare blind ratings.
- **Voice settings** — Higher stability can sound flatter; lower can drift. Tune per **persona** or map from orchestrator **emotion** (optional product feature).
- **Text fed to ElevenLabs** — The micro-behavior engine splits text and inserts pauses; overly fragmented segments can sound choppy. Tune segmentation for **speakability**, not only realism metadata.

---

## 4. Suggested sequencing

| Phase | Focus | Why |
| ----- | ----- | --- |
| A | Logging: STT raw + normalized + confidence + final LLM input | Find whether errors are ASR, normalization, or model |
| B | Vocabulary hints + normalization tables from real sessions | High ROI for domain-heavy sales language |
| C | Confidence / length gating + clarification copy | Stops wrong homeowner replies when STT is unsure |
| D | OpenAI prompt + temperature / token budget | Better answers given a correct transcript |
| E | ElevenLabs model + voice_settings + micro-behavior text | Natural delivery of good text |

---

## Related docs

- [PRD_latency_optimization.md](./PRD_latency_optimization.md) — VAD-triggered finalization (latency; also interacts with **cutoff** risk)
- [EMOTION_SIMULATION_ENGINE.md](./EMOTION_SIMULATION_ENGINE.md) — What the orchestrator tells the LLM each turn
- [CODEX_PROMPT_STT_FLOW.md](../../CODEX_PROMPT_STT_FLOW.md) — Deepgram finalize / `speech_final` behavior and logging ideas
