# Codex Handoff — DoorDrill STT Latency Fix

**Date:** 2026-03-09
**Owner:** Cale
**Priority:** High — STT taking 12-15s per turn; target ≤500ms

---

## Context

DoorDrill is a FastAPI + WebSocket voice-drill app. The speech-to-text pipeline uses Deepgram via a persistent, session-scoped WebSocket (`DeepgramSttClient` in `backend/app/services/provider_clients.py`). A recent refactor introduced a bug where the Deepgram socket was opened with a hardcoded `codec=opus` in `start_session()`, but the real audio arriving from the mobile client is `linear16/WAV`. The encoding mismatch caused Deepgram to return empty transcripts, the `if not transcript: continue` guard fired on every message, and the loop always hit the 10-second timeout. Result: STT was taking 12-15s per turn instead of ~500ms.

---

## Step 1 — Verify the current code state

Before writing any code, **inspect the current `DeepgramSttClient` in `backend/app/services/provider_clients.py`** and confirm whether the lazy-open fix is already in place or still needs to be written.

The correct (fixed) behavior is:

- `start_session(session_id)` → **only** adds `session_id` to `self._session_ids`. Does NOT open any WebSocket.
- `_stream_utterance(payload, audio_bytes, hint)` → calls `_get_or_open_session(session_id, payload=payload)` which opens the WebSocket lazily on first use, using the utterance's actual codec from `payload`.
- Subsequent turns in the same session reuse the already-open socket (same `listen_url`). If the codec changes, `_get_or_open_session` detects the `listen_url` mismatch and reconnects automatically.
- `end_session(session_id)` → sends `{"type": "CloseStream"}`, closes the socket, cancels the keepalive task, removes from `self._sessions` and `self._session_ids`.

**If the fix is already present:** skip to Step 2 (run the diagnostic).
**If `start_session()` still opens a socket with hardcoded `codec=opus`:** implement the fix as described above. Key invariants:
  - `self._session_ids: set[str]` tracks registered sessions.
  - `self._sessions: dict[str, _DeepgramSessionState]` holds open sockets (keyed by `session_id`).
  - `_listen_url(payload)` already exists and correctly derives the Deepgram URL from the utterance's `content_type`, `codec`, `sample_rate`, and `channels`.
  - `_open_session(session_id, payload)` already exists and handles the websockets connection + keepalive loop.

---

## Step 2 — Run the diagnostic script

```bash
cd backend
python debug_deepgram_session.py
```

**Pass criteria** (check each line of the `[utterance complete]` summary):
- `hit_timeout=False` for every utterance
- `total_ms < 1000` for every utterance (ideally 300-700ms)
- `session_type=reused_session turn_2` reuses the same WebSocket as `turn_1` (you'll see the same `ws_id` in the log header)

If `hit_timeout=True` or `total_ms > 10000`, the fix is not working. Debug using the per-message log printed by the script — specifically look for `Results` messages with empty `transcript=` field, which indicates the codec mismatch is still active.

---

## Step 3 — Run the Alembic migration

Migration `0027` adds `BIGINT` support for the `first_response_latency_ms` column (previously `INTEGER`, which overflows for large latency values).

```bash
cd backend
alembic upgrade head
```

Expected: `Running upgrade ... -> 20260309_0027, turn_metrics_latency_bigint` (or similar). No errors.

---

## Step 4 — Stress test without TTS (round-trip sanity check)

```bash
cd backend
python stress_test.py --turns 4 --skip-tts
```

**Pass criteria:**
- All 4 turns complete without error
- STT latency avg ≤ 1000ms per turn
- Round-trip avg ≤ 2000ms per turn (LLM first token already ~1.3-1.5s, so STT must not be the bottleneck)

---

## Step 5 — Full E2E stress test (with TTS)

```bash
cd backend
python stress_test.py --turns 4
```

**Pass criteria:**
- All 4 turns complete without error
- Round-trip avg ≤ 4000ms per turn (includes ElevenLabs TTS streaming)

---

## Files to Know

| File | Purpose |
|------|---------|
| `backend/app/services/provider_clients.py` | `DeepgramSttClient` — the class being fixed |
| `backend/app/voice/ws.py` | WebSocket handler; calls `providers.stt.start_session(session_id)` at ~line 150 and `providers.stt.end_session(session_id)` at ~line 914 |
| `backend/debug_deepgram_session.py` | Diagnostic — run this to verify the fix |
| `backend/stress_test.py` | Full pipeline test |
| `backend/alembic/versions/20260309_0027_turn_metrics_latency_bigint.py` | The pending migration |

---

## Performance Targets (post-fix)

| Metric | Current (broken) | Target |
|--------|-----------------|--------|
| STT latency | 12-15s | ≤ 500ms |
| LLM first token | ~1.3-1.5s | ✅ already good |
| Round-trip (no TTS) | ~14-16s | ≤ 2s avg |
| Round-trip (with TTS) | ~15-17s | ≤ 4s avg |

---

## Key Technical Notes

- **Codec mismatch root cause:** Deepgram's streaming API requires the codec to be specified in the WebSocket URL query params at connection time (e.g. `?encoding=linear16&sample_rate=16000`). Opening the socket with `encoding=opus` and then sending `linear16` PCM/WAV data causes Deepgram to silently return empty transcripts — it doesn't return an error.
- **Keepalive:** `_DeepgramSessionState.keepalive_task` sends `{"type": "KeepAlive"}` every 10s to hold the socket open between turns. This is correct behavior — do not remove it.
- **Lock:** `state.lock` serializes concurrent utterances on the same session. This is intentional — do not remove it.
- **Fallback:** If Deepgram fails or `api_key` is not set, `DeepgramSttClient` falls back to `MockSttClient` which echoes `transcript_hint` from the payload. This is the expected behavior for local dev.
- **`ws.py` call site:** `start_session` is called once per WebSocket connection at line ~150. `end_session` is called in the `finally` block at line ~914. No changes needed in `ws.py`.
