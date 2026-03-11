# DoorDrill — Production Readiness Checklist

> **How to use this document**: Work through each section top to bottom. Every item has a verification step — the item is not done until you can confirm it, not just implement it. Items marked **🔴 BLOCKER** must be completed before any traffic reaches production. Items marked **🟡 IMPORTANT** should be completed before launch but will not cause immediate data loss or security breaches. Items marked **🟢 NICE-TO-HAVE** are improvements that reduce operational burden over time.

---

## Table of Contents

1. [Security & Authentication](#1-security--authentication)
2. [Database & Migrations](#2-database--migrations)
3. [WebSocket & Voice Pipeline](#3-websocket--voice-pipeline)
4. [STT Pipeline (Deepgram)](#4-stt-pipeline-deepgram)
5. [LLM Pipeline (OpenAI / Anthropic)](#5-llm-pipeline-openai--anthropic)
6. [TTS Pipeline (ElevenLabs)](#6-tts-pipeline-elevenlabs)
7. [Storage & Artifacts](#7-storage--artifacts)
8. [Redis & Event Buffer](#8-redis--event-buffer)
9. [Mobile App (Expo / React Native)](#9-mobile-app-expo--react-native)
10. [Infrastructure & Environment](#10-infrastructure--environment)
11. [CORS & Network Hardening](#11-cors--network-hardening)
12. [Rate Limiting & Abuse Prevention](#12-rate-limiting--abuse-prevention)
13. [Error Handling & Recovery](#13-error-handling--recovery)
14. [Observability & Monitoring](#14-observability--monitoring)
15. [Performance Validation](#15-performance-validation)
16. [Test Coverage Verification](#16-test-coverage-verification)
17. [Data Integrity & Privacy](#17-data-integrity--privacy)
18. [Deployment & Rollback](#18-deployment--rollback)
19. [Third-Party Provider Hardening](#19-third-party-provider-hardening)
20. [Pre-Launch Smoke Test Protocol](#20-pre-launch-smoke-test-protocol)

---

## 1. Security & Authentication

### 1.1 🔴 BLOCKER — Rotate the default JWT secret

**Risk**: The default `jwt_secret` is `"dev-jwt-secret-change-me"` (hardcoded in `app/core/config.py` line 27). Any attacker who reads the source code or `.env.example` can mint valid JWTs for any user.

**Fix**: Generate a cryptographically random 64-byte secret and set it in the production `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set `JWT_SECRET=<generated-value>` in production. Never commit the production secret to version control.

**Verification**: Start the server with a freshly generated secret. Tokens signed with the old `dev-jwt-secret-change-me` value must be rejected with HTTP 401.

---

### 1.2 🔴 BLOCKER — Enable `AUTH_REQUIRED=true` in production

**Risk**: `auth_required` defaults to `False` in `app/core/config.py`. With this flag off, all REST endpoints and the WebSocket voice endpoint are accessible without a token, meaning any client can start drill sessions and consume Deepgram, OpenAI, and ElevenLabs API quota.

**Fix**: Set `AUTH_REQUIRED=true` in the production `.env`.

**Verification**: Make an unauthenticated `GET /api/rep/sessions` request. The server must return HTTP 401. Attempt to open the `/ws/voice` WebSocket without a token query param — the connection must be rejected with a 403 close frame.

---

### 1.3 🔴 BLOCKER — Confirm `/uploads` static file directory does not expose raw audio payloads

**Risk**: `app/main.py` mounts `StaticFiles(directory="uploads")` at `/uploads`. If the `uploads/` folder is writable by the application and also publicly served, an attacker can upload arbitrary files (or the app can accidentally write audio chunks there) and read them back without authentication.

**Fix**: Either remove the `/uploads` static mount in production and serve user-uploaded assets only via presigned S3/object-storage URLs, or add an authentication middleware that gates the `/uploads` path. Verify the `uploads/` directory only contains assets explicitly intended to be public (e.g., scenario images). Audio session artifacts must never land here.

**Verification**: Confirm `SessionArtifact.storage_key` values (format: `sessions/{session_id}/canonical_transcript.json`) are stored in object storage, not the local `uploads/` directory. Run `ls uploads/` on the production server and confirm no `.wav` or `.json` session files are present.

---

### 1.4 🔴 BLOCKER — Validate JWT audience and issuer if using an external IdP

**Risk**: `jwt_audience` and `jwt_issuer` both default to `None`. If you later wire up Auth0, Cognito, or Firebase, tokens from other projects (same secret, different audience) will be accepted unless these claims are validated.

**Fix**: If using an external IdP, set `JWT_AUDIENCE` and `JWT_ISSUER` to match the values the IdP embeds in tokens. The `_decode_bearer_token` function in `app/core/auth.py` already reads these fields — they just need to be populated.

**Verification**: Create a test token with a different `aud` claim. Confirm the server returns HTTP 401 when `JWT_AUDIENCE` is configured and the token's audience does not match.

---

### 1.5 🟡 IMPORTANT — Disable debug endpoints and auto-generated docs in production

**Risk**: FastAPI exposes `/docs` (Swagger UI) and `/redoc` (ReDoc) by default. These pages enumerate every endpoint, parameter, and schema, accelerating attacker reconnaissance.

**Fix**: Disable docs when `ENVIRONMENT=production`:

```python
app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)
```

**Verification**: `GET /docs` returns HTTP 404 in production. `GET /openapi.json` returns HTTP 404.

---

### 1.6 🟡 IMPORTANT — Rotate all API keys if any were committed to git history

**Risk**: Even if `.env` files are now gitignored, old commits may contain `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, etc.

**Fix**: Run `git log --all -p | grep -E 'API_KEY|SECRET|PASSWORD'` to scan history. If any keys appear, rotate them immediately in each provider's dashboard and generate new values. This must be done before deployment — keys in git history are permanently leaked.

**Verification**: All keys found in git history are deactivated in each provider's dashboard. New keys are only set via environment variables and are not checked in anywhere.

---

### 1.7 🟡 IMPORTANT — Apply RBAC gate to `client.session.end` WebSocket event

**Risk**: Any authenticated user (even a rep from a different org) who can open a WebSocket can send `client.session.end` with a `session_id` they do not own, potentially terminating another user's live drill session. The `ws.py` handler should validate that the session's `rep_id` matches the authenticated actor before acting on end events.

**Fix**: In the `client.session.end` handler in `ws.py`, confirm `session.rep_id == actor.user_id` (or `actor.role in {"manager", "admin"}` for override). If not, close the WebSocket with code 4003.

**Verification**: Open two WebSocket connections as two different reps. Send `client.session.end` with session_id belonging to the first rep from the second rep's connection. Confirm the second rep's request is rejected.

---

### 1.8 🟢 NICE-TO-HAVE — Add access-token rotation on refresh

**Risk**: With a 30-minute access token TTL and 14-day refresh TTL, a stolen refresh token grants 14 days of access. Consider refresh token rotation (invalidate on use, issue a new one) to limit replay windows.

**Verification**: After a refresh endpoint call, the old refresh token must return HTTP 401.

---

## 2. Database & Migrations

### 2.1 🔴 BLOCKER — Apply all pending Alembic migrations before going live

**Risk**: The latest migration is `0031_manager_onboarding_completed_at.py`. Notably, `0027_turn_metrics_latency_bigint.py` changes `first_response_latency_ms` from INTEGER to BIGINT. Running the app against an unupgraded schema will cause runtime errors as soon as the first session with a latency > 2,147,483,647ms (unlikely but possible after retries) is committed.

**Fix**: Run migrations against the production database:

```bash
cd backend
alembic upgrade head
```

**Verification**: `alembic current` shows `0031` as the active revision with no pending migrations. Cross-check by running `alembic history` and confirming all 31 migrations are applied.

---

### 2.2 🔴 BLOCKER — Switch production `DATABASE_URL` from SQLite to PostgreSQL

**Risk**: The default `DATABASE_URL=sqlite:///./doordrill.db` uses SQLite. SQLite has no WAL mode enabled here, no concurrent write support for async workloads, and `db.py` enables `check_same_thread=False` which masks threading errors. A multi-worker Uvicorn deployment with SQLite will produce `database is locked` errors under any real concurrent load.

**Fix**: Set `DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/doordrill` in the production `.env`. Also remove the SQLite-specific `connect_args={"check_same_thread": False}` branch in `app/db/session.py` to avoid silently masking thread safety issues in future.

Note: The `sslmode=require` branch in `session.py` already handles PostgreSQL correctly. Verify the Postgres user has the minimum required privileges (SELECT, INSERT, UPDATE, DELETE on application tables; no DROP TABLE).

**Verification**: `DATABASE_URL` does not contain `sqlite` in any production config file. `alembic upgrade head` runs successfully against the Postgres instance. A live stress test with `--concurrent 3` produces no `database is locked` errors.

---

### 2.3 🔴 BLOCKER — Configure a production connection pool (not SQLAlchemy defaults)

**Risk**: `session.py` creates the engine with no explicit pool settings. SQLAlchemy defaults to `pool_size=5, max_overflow=10`. Under concurrent drill sessions (each with its own DB writes), connection exhaustion causes `TimeoutError: QueuePool limit` errors that manifest as 500s.

**Fix**: Tune pool settings based on your Postgres server's `max_connections` limit:

```python
engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,   # recycle connections older than 30min
    pool_pre_ping=True,
    echo=False,
    future=True,
)
```

`pool_pre_ping=True` is already set and will discard dead connections before handing them out.

**Verification**: Run `stress_test.py --concurrent 5 --turns 4` and monitor Postgres `pg_stat_activity` — no queries should be waiting on pool acquisition.

---

### 2.4 🟡 IMPORTANT — Add missing database indexes for high-frequency query patterns

**Risk**: The following queries appear in hot paths with no verified index coverage:

- `SessionEvent` lookups by `event_id` (uniqueness check in `_flush_sync`) — without a unique index, the `SELECT` before each insert is a full table scan as the events table grows.
- `SessionTurn` queries ordered by `turn_index` for `compact_session`.
- `Assignment` lookups by `rep_id` and `status` in the rep dashboard API.

**Fix**: Verify migrations create these indexes. If any are missing, add an Alembic migration:

```python
op.create_index("ix_session_event_event_id", "session_events", ["event_id"], unique=True)
op.create_index("ix_session_turn_session_turn_idx", "session_turns", ["session_id", "turn_index"])
op.create_index("ix_assignment_rep_status", "assignments", ["rep_id", "status"])
```

**Verification**: Run `EXPLAIN ANALYZE` on the three queries above against the production database. All three must show `Index Scan` or `Index Only Scan`, not `Seq Scan`.

---

### 2.5 🟡 IMPORTANT — Back up the database before and after each migration run

**Risk**: Alembic `upgrade head` running `ALTER COLUMN` (e.g., migration 0027 changes a column type) can fail mid-migration, leaving the schema in an inconsistent state. Without a backup, recovery requires manual SQL.

**Fix**: Before every production migration:
```bash
pg_dump -Fc doordrill > doordrill_pre_migration_$(date +%Y%m%d%H%M%S).dump
alembic upgrade head
pg_dump -Fc doordrill > doordrill_post_migration_$(date +%Y%m%d%H%M%S).dump
```

**Verification**: Both dump files exist and are non-empty. Test `pg_restore --list` on each to confirm structural integrity.

---

### 2.6 🟡 IMPORTANT — Validate `_flush_sync` thread safety in production workers

**Risk**: `ledger_service.py`'s `_flush_sync` creates its own `SessionLocal()` database session in the thread pool executor. This is correct design — the session is NOT shared with the async context. However, confirm that `SessionLocal` is initialized before any executor call, not lazily after app startup. If `init_db()` hasn't finished by the time the first executor fires, the session factory may not have the correct engine bound.

**Fix**: The `lifespan` handler calls `init_db()` synchronously before the app begins serving. Verify that `engine` is created at module import time (it is, in `session.py`) and `SessionLocal` is bound to it. No change needed if confirmed.

**Verification**: Write a pytest that calls `flush_buffered_events` with 10 events in a thread pool without first touching `get_db()`. All events must be persisted.

---

### 2.7 🟢 NICE-TO-HAVE — Set `statement_timeout` on the PostgreSQL role

**Risk**: A runaway analytics query (e.g., `compact_session` on a session with thousands of turns) can hold a lock indefinitely. Setting a role-level `statement_timeout` caps this.

```sql
ALTER ROLE doordrill_app SET statement_timeout = '30s';
```

---

## 3. WebSocket & Voice Pipeline

### 3.1 🔴 BLOCKER — Confirm `first_audio_started.wait()` is fully removed from `ws.py`

**Risk**: This was the primary cause of the 5.5-second stall. If any copy of the old instrumentation code remains (e.g., in a feature branch that gets merged), the stall reappears immediately.

**Fix**: Search for all remaining occurrences:
```bash
grep -r "first_audio_started" backend/app/
```

Expected result: zero matches. If any appear, remove them.

**Verification**: Zero grep matches. Confirm `stream_tts_for_plan` signature in `ws.py` does not include a `first_audio_started` parameter.

---

### 3.2 🔴 BLOCKER — Validate WebSocket authentication enforcement

**Risk**: `ws.py` calls `resolve_ws_actor_with_query` on connect. Confirm that if authentication fails, the WebSocket is closed before any drill state is allocated (no `ProviderSuite` sessions opened, no `DrillSession` record created).

**Fix**: Audit the connect handler in `ws.py`. The auth resolution must happen before the `await ws.accept()` call (or immediately after if the framework requires accept-before-reject). If the actor is None and `AUTH_REQUIRED=true`, close with code 4001.

**Verification**: Connect to `/ws/voice` with an expired token. The server must close the socket with a 4001 code before any DB records are created.

---

### 3.3 🟡 IMPORTANT — Handle WebSocket ping/pong keepalive timeout gracefully

**Risk**: `WS_KEEPALIVE_TIMEOUT_SECONDS = 120` and `WS_KEEPALIVE_INTERVAL_SECONDS = 30` are set in `ws.py`. If a mobile client goes to background (iOS suspends network), the server will wait up to 120s before detecting the dead connection. During that time, all associated state (Deepgram WebSocket, asyncio tasks, DB session) is held open.

**Fix**: Confirm the keepalive task cancels all associated tasks (TTS tasks, STT session, ledger flush loop) as soon as the keepalive timeout fires. Add a `finally:` block in the keepalive task that calls `providers.stt.end_session(session_id)` and cancels any pending `tts_tasks`.

**Verification**: Connect a client, kill the network interface without sending a close frame, and wait 130 seconds. Confirm via logs that `session.keepalive_timeout` is emitted and that the Deepgram WebSocket is closed within 10 seconds of that event.

---

### 3.4 🟡 IMPORTANT — Limit maximum concurrent WebSocket sessions per user

**Risk**: A single rep account could open many WebSocket connections simultaneously (mobile app crash loop, automation attack), consuming Deepgram and ElevenLabs API quota and filling the connection pool.

**Fix**: Track open sessions per `user_id` in a shared dict (or Redis set in multi-worker deployments). Reject connections that would exceed the per-user limit (suggest: 2 concurrent sessions max — one active, one reconnecting).

**Verification**: Open 3 concurrent WebSocket connections as the same rep. The third connection must be closed with code 4029 (Too Many Connections).

---

### 3.5 🟡 IMPORTANT — Confirm `asyncio.shield` behavior under worker shutdown

**Risk**: When the Uvicorn worker receives SIGTERM, all running coroutines are cancelled. `asyncio.shield(flush_future)` in `flush_buffered_events` will catch the `CancelledError` and re-await the future — but only if the event loop is still running. If SIGTERM causes the loop to stop before the shielded future completes, in-flight events are lost.

**Fix**: In the application's shutdown lifecycle (the `lifespan` context manager's cleanup phase after `yield`), explicitly drain all buffered events for all active sessions before yielding control to Uvicorn's shutdown. If using Redis buffer, this is safe because events survive the process restart. If using `InMemoryEventBuffer` (the fallback), the flush must happen synchronously during shutdown.

**Verification**: Start a drill session, send 20 events, send SIGTERM to the worker. Confirm all 20 events appear in `session_events` table after restart.

---

### 3.6 🟡 IMPORTANT — Validate `MAX_RUNTIME_PAUSE_MS` under load

**Risk**: `MAX_RUNTIME_PAUSE_MS = 60` means the main `ws.py` loop spins every 60ms regardless of activity. Under high concurrency (50+ concurrent sessions on a single worker), this idle spinning multiplies CPU load. Consider making the idle pause adaptive or event-driven.

**Verification**: Profile CPU usage with 20 concurrent sessions, all in an idle state (no audio being sent). CPU should be minimal, not proportional to session count.

---

### 3.7 🟢 NICE-TO-HAVE — Add a session-level maximum duration guard

**Risk**: If a rep starts a drill and never sends `client.session.end` (app crash, network loss, zombie session), the server holds the session open indefinitely until the keepalive timeout. Consider a hard maximum session duration (e.g., 30 minutes) after which the session is forcibly closed and graded.

---

## 4. STT Pipeline (Deepgram)

### 4.1 🔴 BLOCKER — Confirm `_listen_url` does not set both `mimetype` and `encoding` simultaneously

**Risk**: Setting both `mimetype` and `encoding` on a Deepgram streaming URL produces empty transcripts. This was the original root cause of the 12–15s STT latency. The fix was applied — confirm it held.

**Fix**: Grep for the current state of `_listen_url` in `provider_clients.py`:

```bash
grep -A 20 "_listen_url" backend/app/services/provider_clients.py
```

Confirm the logic is:
- `codec == "opus"` → `encoding=opus` only, no `mimetype`
- `content_type in ("audio/mp4", "audio/webm", "audio/mpeg")` → `mimetype=...` only, no `encoding`
- everything else (WAV/LinearPCM) → `encoding=linear16` only, no `mimetype`

**Verification**: Run `pytest tests/test_deepgram_stt_client.py -v`. All 8 `_listen_url` codec tests must pass. Additionally, run a live session with WAV audio and confirm `stt.transcript` events are emitted within 1.5s of audio upload.

---

### 4.2 🔴 BLOCKER — Confirm `start_session` does NOT open a WebSocket

**Risk**: The original bug was `start_session()` opening the Deepgram WebSocket with a hardcoded `codec=opus`, then real audio arriving as `linear16`, causing a codec mismatch that Deepgram silently treated as empty input. The fix (lazy WebSocket open in `_stream_utterance`) was applied — confirm it held.

**Fix**: Grep for WebSocket creation in `start_session`:

```bash
grep -A 10 "async def start_session" backend/app/services/provider_clients.py
```

Confirm the method only calls `self._session_ids.add(session_id)` and returns. No `websockets.connect()` call should appear inside `start_session`.

**Verification**: Run `pytest tests/test_deepgram_stt_client.py::test_start_session_does_not_open_websocket -v`.

---

### 4.3 🟡 IMPORTANT — Test Deepgram reconnect on `ConnectionClosed`

**Risk**: Deepgram terminates idle streaming WebSocket connections after ~30 seconds of silence. The retry logic in `_stream_utterance` re-opens the connection, but the `retried` flag only allows one retry. If the connection closes again on the same utterance (rare but possible under network instability), the second `ConnectionClosed` propagates as an error.

**Fix**: Consider increasing the retry count from 1 to 2 for `ConnectionClosed`, with exponential backoff capped at 1s. This handles transient Deepgram gateway resets without infinite looping.

**Verification**: Mock a `ConnectionClosed` on the second attempt. Confirm the third attempt succeeds if you've increased max retries, or that the error is surfaced cleanly as a `stt.error` WebSocket event to the client (not a silent drop or server crash).

---

### 4.4 🟡 IMPORTANT — Set Deepgram connection timeout

**Risk**: `_stream_utterance` opens a WebSocket to Deepgram. If Deepgram's API is down or routing is slow, `websockets.connect()` may hang indefinitely. The `provider_timeout_seconds = 10.0` setting in config is not consistently applied to the Deepgram WebSocket open call.

**Fix**: Wrap the `websockets.connect()` call inside `asyncio.wait_for(..., timeout=settings.provider_timeout_seconds)`. If it times out, close the session and emit a `stt.error` event with a recoverable error code.

**Verification**: Mock `websockets.connect` to sleep for 15 seconds. Confirm the utterance fails within `provider_timeout_seconds + 1s` and the session continues (or closes gracefully).

---

### 4.5 🟡 IMPORTANT — Validate Deepgram `endpointing` parameter is correct for drill pacing

**Risk**: `endpointing=300` (300ms of silence → end of utterance) is set in `_listen_url`. For door-to-door sales training, reps often pause mid-sentence to think. 300ms may cause mid-sentence cuts that send incomplete STT transcripts to the LLM, degrading coaching quality.

**Fix**: A/B test `endpointing=500` (500ms) vs `endpointing=300` in staging. Evaluate transcript completion rates. Consider making `endpointing` a configurable setting via `app/core/config.py`.

**Verification**: Record 5 sample rep utterances with natural mid-sentence pauses > 300ms. Confirm none are prematurely cut with `endpointing=500`.

---

### 4.6 🟢 NICE-TO-HAVE — Add Deepgram `utterance_end_ms` for clean sentence boundaries

**Risk**: `interim_results=true` sends partial transcripts that the server must stitch together. Using Deepgram's `utterance_end_ms` parameter in addition to endpointing gives a cleaner "utterance complete" signal, reducing partial-transcript processing in `ws.py`.

---

## 5. LLM Pipeline (OpenAI / Anthropic)

### 5.1 🔴 BLOCKER — Confirm `homeowner_token_budget` is applied and not overridden by default

**Risk**: `homeowner_token_budget(stage)` was added to `ws.py` to control LLM verbosity. If the calling code still passes a hardcoded `max_tokens=80` (the old default) instead of using the stage-aware budget, the homeowner AI will be uniformly verbose regardless of stage.

**Fix**: Grep for all `stream_reply` calls in `ws.py` and confirm each uses `homeowner_token_budget(stage)`:

```bash
grep -n "stream_reply\|max_tokens" backend/app/voice/ws.py
```

**Verification**: Start a drill and observe LLM output token counts per stage. `door_knock` stage responses must be ≤15 tokens. `considering` stage responses must be ≤45 tokens. Confirm via the `session_turns` table: `ended_at - started_at` should be shorter for door_knock turns than for considering turns.

---

### 5.2 🟡 IMPORTANT — Handle LLM API rate limit responses (HTTP 429)

**Risk**: OpenAI and Anthropic both return HTTP 429 with a `Retry-After` header when rate limits are hit. The current `stream_reply` implementation does not handle 429 — it will propagate as an uncaught exception, silently dropping the LLM response and leaving the drill in a broken state.

**Fix**: Wrap `stream_reply` calls with retry logic for 429 responses:

```python
for attempt in range(3):
    try:
        async for token in providers.llm.stream_reply(...):
            ...
        break
    except RateLimitError:
        if attempt == 2:
            raise
        await asyncio.sleep(2 ** attempt)
```

**Verification**: Mock `stream_reply` to raise `RateLimitError` on the first call and succeed on the second. Confirm the drill continues and the rep receives a response.

---

### 5.3 🟡 IMPORTANT — Validate RAG context injection does not exceed model context window

**Risk**: `ws.py` injects pricing chunks (k=3) and competitor chunks (k=2) as `company_context` into the orchestrator's system prompt. If each chunk is large (e.g., 1000 tokens), and the base system prompt is already 2000 tokens, plus conversation history, the total could approach 8192 tokens for GPT-4o-mini, causing truncation of the most recent turns.

**Fix**: Apply a maximum token cap to the RAG context block. Before injecting, measure token count (using `tiktoken` for OpenAI or a character-count heuristic). If the RAG context would push the total system prompt over 3000 tokens, trim the lowest-scored chunks first.

**Verification**: Create a scenario with 5 very long pricing documents. Confirm the system prompt sent to OpenAI is under 4000 tokens total, including conversation history.

---

### 5.4 🟡 IMPORTANT — Add LLM content safety filter for homeowner responses

**Risk**: The homeowner AI could generate responses that are off-brand, offensive, or nonsensical under adversarial inputs (e.g., a rep saying something that jailbreaks the prompt). For a B2B sales training product, this is a product-safety risk.

**Fix**: Add a post-generation check that validates homeowner output against a simple word list or a secondary classification call before TTS. If flagged, substitute a neutral fallback response.

**Verification**: Send a rep utterance containing a known jailbreak pattern. Confirm the homeowner response is either the neutral fallback or a reasonable on-topic response.

---

### 5.5 🟢 NICE-TO-HAVE — Cache system prompts per (scenario_id, stage) to reduce per-turn computation

**Risk**: If `prepare_rep_turn` or the orchestrator rebuilds the full system prompt on every turn, this adds 5–20ms of CPU work per turn. Caching the prompt template per scenario+stage and only updating the conversation history portion reduces this overhead.

---

## 6. TTS Pipeline (ElevenLabs)

### 6.1 🔴 BLOCKER — Validate that `tts_emit_lock` prevents audio overlapping

**Risk**: `tts_emit_lock` serializes playback of TTS sentences. If two sentences are enqueued simultaneously and the lock is not held correctly, the client receives interleaved audio chunks from different sentences, producing garbled speech.

**Fix**: Audit `ws.py` to confirm `tts_emit_lock` is an `asyncio.Lock` held for the entire duration of streaming each sentence's audio chunks. No other coroutine should be able to emit audio to the client WebSocket while a sentence is streaming.

**Verification**: Trigger a multi-sentence LLM response (e.g., a `considering` stage reply). Monitor the WebSocket frame log on the client side. Audio chunk sequences must be monotonically ordered — no interleaving of sentence 1 and sentence 2 chunks.

---

### 6.2 🟡 IMPORTANT — Handle ElevenLabs streaming timeout

**Risk**: `TTS_STREAM_TIMEOUT_SECONDS = 6`. If ElevenLabs takes > 6 seconds to start streaming the first audio byte, the TTS task times out. Confirm the timeout applies to the streaming connection as a whole, not just the first byte. Also confirm the timeout cancellation is handled without leaving the `tts_emit_lock` in a locked state.

**Fix**: Wrap the ElevenLabs streaming call in `asyncio.wait_for(tts_stream_generator, timeout=TTS_STREAM_TIMEOUT_SECONDS)`. In the `except asyncio.TimeoutError` handler, ensure the lock is released and a `tts.error` event is emitted to the client.

**Verification**: Mock ElevenLabs to delay 8 seconds before yielding the first chunk. Confirm the session recovers gracefully: the lock is released, the next sentence's TTS can proceed, and the client receives a `tts.error` event.

---

### 6.3 🟡 IMPORTANT — Confirm audio mode is only set once per queue drain cycle on mobile

**Risk**: `configurePlaybackAudioMode()` was being called inside `playAudioChunk()` (once per chunk). The fix moves it to once per `drainAudioQueue()` invocation. Confirm this change was applied in `SessionScreen.tsx`.

**Fix**: Grep for `configurePlaybackAudioMode` in the mobile source:

```bash
grep -n "configurePlaybackAudioMode" mobile/src/screens/SessionScreen.tsx
```

Confirm it appears exactly once, outside the `while` loop that drains chunks.

**Verification**: Play a multi-chunk TTS response (>3 audio chunks). Monitor iOS system logs. `AVAudioSession` mode changes should appear exactly once per drain cycle, not once per chunk.

---

### 6.4 🟡 IMPORTANT — Validate ElevenLabs voice ID is set for production

**Risk**: `elevenlabs_voice_id` defaults to `None`. If not set, ElevenLabs falls back to a default voice or returns an error. For production, the specific voice ID must be configured.

**Fix**: Set `ELEVENLABS_VOICE_ID=<your-voice-id>` in the production `.env`.

**Verification**: Confirm `settings.elevenlabs_voice_id` is not None at app startup. Add a startup health check that warns (but does not crash) if `TTS_PROVIDER=elevenlabs` and `ELEVENLABS_VOICE_ID` is not set.

---

### 6.5 🟢 NICE-TO-HAVE — Pre-warm ElevenLabs connection at session start

**Risk**: The first TTS request after a new session opens incurs TCP handshake + TLS latency (~100–200ms) on top of ElevenLabs generation time. Pre-opening the HTTP connection (or making a dummy warmup request) can reduce first-sentence latency.

---

## 7. Storage & Artifacts

### 7.1 🔴 BLOCKER — Configure object storage credentials for production

**Risk**: `object_storage_access_key` and `object_storage_secret_key` both default to `None`. The `StorageService` will fail silently or raise unhandled exceptions if called without valid credentials. Session artifacts (canonical transcripts) will not be persisted.

**Fix**: Set in production `.env`:
```
OBJECT_STORAGE_ENDPOINT=https://s3.amazonaws.com  # or your S3-compatible endpoint
OBJECT_STORAGE_REGION=us-east-1
OBJECT_STORAGE_ACCESS_KEY=<aws-access-key-id>
OBJECT_STORAGE_SECRET_KEY=<aws-secret-access-key>
STORAGE_BUCKET=doordrill-session-artifacts-prod
```

**Verification**: Complete a full drill session. Confirm a `SessionArtifact` record is created with `artifact_type="canonical_transcript"` and `storage_key="sessions/{session_id}/canonical_transcript.json"`. Confirm the JSON object is retrievable via the presigned URL.

---

### 7.2 🟡 IMPORTANT — Verify presigned URL TTL is appropriate

**Risk**: `default_presign_ttl_seconds = 3600` (1 hour). If these URLs are embedded in push notifications or emails that might be opened days later, the links will be broken. If TTL is too short for the expected access pattern (e.g., manager reviews session 2 hours after it completes), links will expire before use.

**Fix**: Review the actual access pattern. Manager review typically happens within 24 hours, so `DEFAULT_PRESIGN_TTL_SECONDS=86400` (24 hours) or `604800` (7 days) may be more appropriate. Do not set TTL to indefinite (0) — this creates permanent public URLs.

**Verification**: Confirm that presigned URLs returned to the dashboard client have a TTL that covers the expected review window.

---

### 7.3 🟡 IMPORTANT — Add CORS configuration to S3 bucket for dashboard access

**Risk**: The React dashboard may attempt to fetch presigned S3 URLs directly in the browser for audio playback. Without a CORS rule on the bucket, these requests will be blocked by the browser's same-origin policy.

**Fix**: Add a CORS configuration to the production S3 bucket:
```json
[{
  "AllowedHeaders": ["*"],
  "AllowedMethods": ["GET"],
  "AllowedOrigins": ["https://app.yourdomain.com"],
  "MaxAgeSeconds": 3600
}]
```

**Verification**: From the dashboard, attempt to play back a session audio artifact. The network request must succeed without CORS errors in the browser console.

---

### 7.4 🟡 IMPORTANT — Prevent storage key collisions

**Risk**: `compact_session` generates `storage_key = f"sessions/{session_id}/canonical_transcript.json"`. If `session_id` is a UUID, collisions are astronomically unlikely. However, if a session is ever re-compacted (e.g., a retry path), the old artifact is silently overwritten. Consider appending a timestamp or version number: `sessions/{session_id}/canonical_transcript_{timestamp}.json`.

**Verification**: Confirm `compact_session` is idempotent: calling it twice produces two `SessionArtifact` DB records (with different `created_at` values) and the latest object in storage is the correct one.

---

## 8. Redis & Event Buffer

### 8.1 🔴 BLOCKER — Confirm Redis is deployed and `REDIS_URL` is set in production

**Risk**: `ws.py` falls back to `InMemoryEventBuffer` if `REDIS_URL` is not set or Redis is unreachable. With `InMemoryEventBuffer`, all buffered events are lost on process restart (e.g., deployment, crash). In a multi-worker setup, events are partitioned across worker processes and cannot be drained by a different worker.

**Fix**: Set `REDIS_URL=redis://<host>:6379/0` in production. Verify Redis is running and reachable before the first deployment. The fallback to `InMemoryEventBuffer` is acceptable only in single-worker development, never in production.

**Verification**: Set `REDIS_URL` and confirm `RedisEventBuffer` is instantiated (not `InMemoryEventBuffer`) by checking startup logs. Push 10 events, restart the worker process, drain events — all 10 must still be present.

---

### 8.2 🟡 IMPORTANT — Confirm Redis TTL is long enough for slow session completions

**Risk**: `RedisEventBuffer` sets `ttl_seconds=1200` (20 minutes). If a drill session is paused (rep goes to background), and the rep returns > 20 minutes later, all buffered events are expired from Redis. When the session resumes, these events will never be flushed to the database.

**Fix**: Increase `ttl_seconds` to at least 3600 (1 hour) to handle distracted reps. Make this value configurable via `app/core/config.py`.

**Verification**: Buffer 10 events in Redis. Wait 25 minutes. Attempt to drain. Confirm events are gone (expected behavior). Increase TTL to 3600. Repeat — events must persist.

---

### 8.3 🟡 IMPORTANT — Authenticate Redis connections in production

**Risk**: `redis_url` is `redis://localhost:6379/0` without authentication. If Redis is exposed (even on a private network), unauthenticated access could allow an attacker to read/modify session event queues.

**Fix**: Set a Redis password: `redis://:yourpassword@localhost:6379/0`. Or use Redis ACLs with a dedicated user for the app.

**Verification**: Attempt to connect to the production Redis without credentials. Connection must be refused with `NOAUTH`.

---

### 8.4 🟡 IMPORTANT — Confirm `drain` is atomic under concurrent flushes

**Risk**: `RedisEventBuffer.drain` uses `LRANGE` followed by `LTRIM`. These two commands are not atomic — a concurrent flush from a second worker could drain the same events simultaneously. Under multi-worker deployment, the same events could be flushed twice, and the `event_id` uniqueness check in `_flush_sync` would deduplicate them, but only if the check is truly idempotent.

**Fix**: Replace `LRANGE + LTRIM` with a Lua script that atomically pops N elements:

```lua
local key = KEYS[1]
local n = tonumber(ARGV[1])
local items = redis.call('LRANGE', key, 0, n-1)
redis.call('LTRIM', key, n, -1)
return items
```

**Verification**: Simulate two concurrent `drain` calls for the same session. Confirm no event appears in the database twice (relying on uniqueness check is a safety net, not a correctness guarantee).

---

## 9. Mobile App (Expo / React Native)

### 9.1 🔴 BLOCKER — Confirm recording codec is `LINEAR PCM` (not M4A) on both iOS and Android

**Risk**: The original bug was `expo-av`'s `HIGH_QUALITY` preset producing M4A (AAC) on iOS, which Deepgram cannot process as `linear16`. The fix (explicit `LINEARPCM` recording options) was applied. Confirm it held.

**Fix**: Verify `audio.ts` recording options:

```bash
grep -A 15 "RECORDING_OPTIONS" mobile/src/services/audio.ts
```

Confirm:
- iOS: `outputFormat: Audio.IOSOutputFormat.LINEARPCM`, `linearPCMBitDepth: 16`, `linearPCMIsBigEndian: false`, `linearPCMIsFloat: false`
- Android: `outputFormat: Audio.AndroidOutputFormat.DEFAULT` (maps to PCM/WAV on Android), `sampleRate: 16000`, `numberOfChannels: 1`
- No `HIGH_QUALITY` preset anywhere

**Verification**: Record a 2-second utterance on a physical iOS device. Read the resulting WAV header bytes. Confirm the file starts with `RIFF` (not `ftypM4A`) and has a `fmt ` chunk with `audioFormat=1` (PCM), `numChannels=1`, `sampleRate=16000`, `bitsPerSample=16`.

---

### 9.2 🔴 BLOCKER — Verify `AudioChunk` type fields match what `_listen_url` reads

**Risk**: `_listen_url` in `provider_clients.py` reads `payload.get("sample_rate")`, `payload.get("channels")`, and `payload.get("codec")`. The updated `AudioChunk` type in `audio.ts` must emit all three fields. If `sampleRate` or `channels` are missing, `_listen_url` falls through to integer defaults (16000/1), which is correct, but a mismatch would silently use wrong values.

**Fix**: Confirm the `stop()` method in `AudioCaptureService` emits:
```typescript
{
  codec: "wav",
  contentType: "audio/wav",
  sampleRate: 16000,
  channels: 1,
  payload: <base64>,
  durationMs: ...,
  createdAt: ...
}
```

Also confirm that the WebSocket message handler that sends `client.audio.chunk` maps these fields to the server-side `payload` dict with the correct key names (`sample_rate`, `channels`, `content_type`, `codec`).

**Verification**: Log the raw JSON of a `client.audio.chunk` event on the server side. Confirm all four fields are present with correct values.

---

### 9.3 🔴 BLOCKER — Ensure microphone permission error is surfaced to the user

**Risk**: `ensurePermission()` throws `Error("Microphone permission is required to run live drills")`. If this error is not caught by the UI layer and displayed to the user, the drill silently fails to start with no feedback.

**Fix**: In the component that calls `audioService.start()`, wrap the call in `try/catch` and display the error message to the user via an alert or toast notification.

**Verification**: Run the app on a simulator/device with microphone permission denied. Tap the microphone button. A user-visible error message must appear within 500ms.

---

### 9.4 🟡 IMPORTANT — Confirm VAD hysteresis constants are applied in `handleStatus`

**Risk**: `VAD_ATTACK_FRAMES=2` and `VAD_RELEASE_FRAMES=5` were added. Confirm `handleStatus` uses the `activePendingFrames` and `silentPendingFrames` counters correctly.

**Fix**: Verify the current implementation:

```bash
grep -A 25 "handleStatus" mobile/src/services/audio.ts
```

Confirm:
- Above threshold: `activePendingFrames++; silentPendingFrames=0;` — only calls `updateSpeaking(true)` when `activePendingFrames >= VAD_ATTACK_FRAMES`
- Below threshold: `silentPendingFrames++; activePendingFrames=0;` — only calls `updateSpeaking(false)` when `silentPendingFrames >= VAD_RELEASE_FRAMES`

**Verification**: Run `jest` mobile tests. The 6 VAD hysteresis test cases must all pass:
1. `activePendingFrames < VAD_ATTACK_FRAMES` → no speaking event
2. `activePendingFrames >= VAD_ATTACK_FRAMES` → speaking=true
3. `silentPendingFrames < VAD_RELEASE_FRAMES` → speaking stays true
4. `silentPendingFrames >= VAD_RELEASE_FRAMES` → speaking=false
5. Single noise spike does not trigger speaking=true
6. `canRecord=false` resets both counters

---

### 9.5 🟡 IMPORTANT — Set minimum audio chunk duration guard

**Risk**: `stop()` in `audio.ts` sets `durationMs: Math.max(180, durationMs)`. This prevents sending 0ms audio chunks that cause Deepgram to return parse errors. However, very short audio (< 300ms) may also produce low-quality transcripts. Evaluate whether `Math.max(300, durationMs)` is more appropriate.

**Verification**: Hold the microphone button for 150ms. The chunk sent to the server must have `durationMs >= 180`. Confirm Deepgram does not return an error for this chunk.

---

### 9.6 🟡 IMPORTANT — Add mobile app version header to WebSocket connections

**Risk**: Without a version header, the server cannot distinguish between old and new app clients during a rolling deployment. If a breaking change is made to the WebSocket protocol, old app versions will malfunction silently.

**Fix**: Add an `X-App-Version` header to the WebSocket connection request in the mobile app. On the server, log the client version for each session.

**Verification**: The WebSocket connection logs on the server include the app version string.

---

### 9.7 🟡 IMPORTANT — Handle `expo-av` recording initialization error on Android

**Risk**: `audio.ts` catches `/recorder not prepared/i` and `/prepare encountered an error/i` errors from expo-av and wraps them in a user-friendly message. Android has several additional failure modes: `MEDIA_RECORDER_ERROR_UNKNOWN`, `MediaRecorder.MEDIA_ERROR_SERVER_DIED`. Confirm these are caught and handled without crashing the app.

**Verification**: On an Android device, revoke microphone permission mid-session. Confirm the app shows an error rather than crashing.

---

### 9.8 🟢 NICE-TO-HAVE — Add offline detection before starting a drill session

**Risk**: If the device has no network connection, the WebSocket connection attempt will fail after a timeout (~30s), during which the user sees nothing. A proactive network check before opening the WebSocket provides an immediate error.

---

## 10. Infrastructure & Environment

### 10.1 🔴 BLOCKER — Set `ENVIRONMENT=production` in the production `.env`

**Risk**: `settings.environment = "dev"` is the default. Various behavior is gated on this: logging verbosity, debug endpoints, error detail exposure. Running a production server with `environment=dev` may expose stack traces in API responses.

**Fix**: `ENVIRONMENT=production` in the production `.env`.

**Verification**: Make a request to a non-existent endpoint. The 404 response body must not contain a Python stack trace.

---

### 10.2 🔴 BLOCKER — Use a production-grade ASGI server, not `uvicorn --reload`

**Risk**: `uvicorn app.main:app --reload` watches the filesystem for changes and restarts on every file modification. This is development-only behavior. In production, use `gunicorn` with `uvicorn` workers for process management and graceful restarts:

```bash
gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 \
  --timeout 120 \
  --graceful-timeout 30 \
  --bind 0.0.0.0:8000
```

**Verification**: The production process does NOT have `--reload` in its arguments. Confirm `ps aux | grep uvicorn` shows the production command.

---

### 10.3 🔴 BLOCKER — Remove `doordrill.db` SQLite file from the repository and server

**Risk**: `doordrill.db` is committed to the repository root. This file may contain real user data (org records, rep profiles, session transcripts) from development/testing. A developer who clones the repo gets a copy of all that data.

**Fix**: Add `*.db` to `.gitignore`. Delete `doordrill.db`, `test_provider_clients.db` from the repository with `git rm --cached`. Wipe any SQLite files from the production server.

**Verification**: `git ls-files | grep ".db"` returns empty. No `.db` files exist in the production server's application directory.

---

### 10.4 🟡 IMPORTANT — Separate production and staging environments completely

**Risk**: Using the same database, Redis, and API keys for both production and staging means a staging test can corrupt production data or exhaust API quota.

**Fix**: Create separate `.env` files for staging and production. Use separate Postgres databases, Redis instances, S3 buckets, and API keys. Never share secrets between environments.

**Verification**: The staging `DATABASE_URL` does not point to the production Postgres host.

---

### 10.5 🟡 IMPORTANT — Configure TLS for all external connections

**Risk**: The database connection in `session.py` uses `sslmode=require` — correct. Confirm that the Redis connection also uses TLS in production (`rediss://` scheme, not `redis://`). Confirm the ElevenLabs and Deepgram base URLs are `https://` (they are in defaults, but verify they're not overridden in production `.env`).

**Verification**: `REDIS_URL` starts with `rediss://`. `DEEPGRAM_BASE_URL` and `ELEVENLABS_BASE_URL` both start with `https://` in production.

---

### 10.6 🟡 IMPORTANT — Configure file upload size validation server-side

**Risk**: `max_upload_size_bytes = 5_242_880` (5MB) is set in config but only enforced if the middleware or API endpoint actually reads this setting. Confirm the upload endpoints in `app/api/` validate file size before writing to disk.

**Verification**: Send a 10MB file to an upload endpoint. The server must return HTTP 413 before writing anything to the `uploads/` directory.

---

## 11. CORS & Network Hardening

### 11.1 🔴 BLOCKER — Restrict CORS `allow_origins` to production domains

**Risk**: `main.py` hardcodes `allow_origins` to `["http://127.0.0.1:5174", "http://localhost:5174", ...]` — local development URLs. In production, these should be replaced with the actual production and staging dashboard domains.

**Fix**: Make CORS origins configurable via `app/core/config.py`:

```python
cors_origins: list[str] = Field(
    default=["http://localhost:5174"],
    alias="CORS_ORIGINS"
)
```

Set `CORS_ORIGINS=https://app.yourdomain.com,https://staging.yourdomain.com` in production.

**Verification**: From a browser on `https://attacker.com`, make a `fetch()` call to the production API. The response must include no `Access-Control-Allow-Origin` header (the browser blocks it). From `https://app.yourdomain.com`, the same request must succeed.

---

### 11.2 🔴 BLOCKER — Remove `allow_methods=["*"]` and `allow_headers=["*"]` in production CORS

**Risk**: `allow_methods=["*"]` and `allow_headers=["*"]` permit all HTTP methods (including `DELETE`, `PATCH`) and all headers from any allowed origin. While this is convenient for development, it's overly permissive. Restrict to the actual methods and headers the frontend uses.

**Fix**: Enumerate the exact methods and headers:

```python
allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Trace-Id"],
```

**Verification**: Send an `OPTIONS` preflight for `CONNECT` method. Server must return a 400 or not include it in `Access-Control-Allow-Methods`.

---

### 11.3 🟡 IMPORTANT — Validate that WebSocket connections cannot bypass CORS

**Risk**: WebSocket connections use the `Origin` header but browsers do not enforce same-origin for WebSocket. A malicious page on `https://attacker.com` can open a WebSocket to your backend if the backend does not validate the `Origin` header on connect.

**Fix**: In the WebSocket connect handler, check `websocket.headers.get("origin")` against the allowed origins list. Reject connections from unknown origins with close code 4003.

**Verification**: Open a WebSocket connection with `Origin: https://attacker.com`. The server must reject it.

---

## 12. Rate Limiting & Abuse Prevention

### 12.1 🔴 BLOCKER — Implement rate limiting on the WebSocket voice endpoint

**Risk**: The `/ws/voice` endpoint has no rate limiting. A malicious actor with a valid JWT can open hundreds of WebSocket connections, each triggering Deepgram, OpenAI, and ElevenLabs API calls, burning through API quota in minutes.

**Fix**: Add `slowapi` or a custom middleware that limits WebSocket connections per authenticated user:
- Max 2 concurrent WebSocket connections per `user_id`
- Max 20 new WebSocket connections per `user_id` per hour

**Verification**: Attempt to open 3 concurrent WebSocket connections as the same user. The third connection must be rejected with close code 4029.

---

### 12.2 🟡 IMPORTANT — Add rate limiting to authentication endpoints

**Risk**: The `/auth/login` endpoint has no brute-force protection. An attacker can attempt millions of password combinations.

**Fix**: Add `slowapi` rate limiting to `POST /auth/login`: 5 attempts per IP per minute. After 5 failures, return HTTP 429 with `Retry-After: 60`.

**Verification**: Send 6 `POST /auth/login` requests from the same IP within 60 seconds. The 6th must return HTTP 429.

---

### 12.3 🟡 IMPORTANT — Add rate limiting to the invite endpoint

**Risk**: The invitation endpoint (`POST /admin/invitations` or similar) could be abused to send spam emails to arbitrary addresses if not rate-limited.

**Fix**: Limit invite creation to 50 per org per day. Alert if the limit is approached.

**Verification**: Create 51 invitations in a single day. The 51st must return HTTP 429.

---

## 13. Error Handling & Recovery

### 13.1 🟡 IMPORTANT — Standardize error events sent over WebSocket

**Risk**: If a server-side error occurs mid-session (e.g., LLM API failure, Deepgram disconnect), the client receives either no event (silent failure) or a raw Python exception message. The client has no way to distinguish recoverable errors (retry) from fatal errors (end session).

**Fix**: Define a standard `server.error` WebSocket event schema:
```json
{
  "type": "server.error",
  "code": "stt_timeout",
  "recoverable": true,
  "message": "Speech recognition timed out. Please try again."
}
```

Map all provider errors to these codes in `ws.py` and emit before closing (for fatal errors) or as warnings (for recoverable ones).

**Verification**: Mock a Deepgram timeout. Confirm the client receives `{"type": "server.error", "code": "stt_timeout", "recoverable": true}` and the UI shows a retry prompt.

---

### 13.2 🟡 IMPORTANT — Confirm session cleanup runs even when WebSocket closes unexpectedly

**Risk**: If the client closes the WebSocket without sending `client.session.end`, the `finally:` block in `ws.py` must still run cleanup: close Deepgram session, flush ledger events, finalize the `DrillSession` record, and cancel any pending TTS tasks.

**Fix**: Audit the `except WebSocketDisconnect` handler and the outer `finally:` block in `ws.py`. Confirm both `providers.stt.end_session(session_id)` and `ledger.flush_buffered_events(...)` are called in all exit paths.

**Verification**: Connect a client, start recording, then force-close the WebSocket (kill the network). Confirm via DB that the `DrillSession` record has `status != IN_PROGRESS` after the server detects the disconnect.

---

### 13.3 🟡 IMPORTANT — Handle `SessionLocal()` connection failure in `_flush_sync`

**Risk**: `_flush_sync` creates `worker_db = SessionLocal()` in a thread. If the database is unreachable (network partition, PostgreSQL restart), this raises an `OperationalError`. The error propagates to `flush_buffered_events`, which propagates to the session loop. Without handling, this terminates the entire WebSocket session.

**Fix**: Wrap the `SessionLocal()` call and the body of `_flush_sync` in `try/except OperationalError`. Log the error and return 0 (events remain in buffer for next flush attempt). Do not re-raise.

**Verification**: Mock `SessionLocal()` to raise `OperationalError`. Confirm the WebSocket session continues normally and emits a `server.warning` log event.

---

### 13.4 🟢 NICE-TO-HAVE — Add structured error codes to all HTTP error responses

**Risk**: `raise HTTPException(status_code=400, detail="some message")` returns a string. If the frontend needs to handle specific error cases differently (e.g., show different UI for "invalid invite token" vs "expired invite token"), it must parse the string. Structured error codes (`{"code": "invite_expired", "message": "..."}`) are more robust.

---

## 14. Observability & Monitoring

### 14.1 🔴 BLOCKER — Add a structured startup log that confirms all required secrets are set

**Risk**: If `DEEPGRAM_API_KEY` or `OPENAI_API_KEY` is missing at startup, the app starts successfully (providers default to mock) but all production API calls silently use mocks. No user-visible error occurs until a drill session is attempted.

**Fix**: Add a startup validation function called from `lifespan`:

```python
def validate_production_config():
    s = get_settings()
    if s.environment == "production":
        assert s.stt_provider != "mock", "STT_PROVIDER must not be 'mock' in production"
        assert s.llm_provider != "mock", "LLM_PROVIDER must not be 'mock' in production"
        assert s.tts_provider != "mock", "TTS_PROVIDER must not be 'mock' in production"
        assert s.deepgram_api_key, "DEEPGRAM_API_KEY is required"
        assert s.openai_api_key or s.anthropic_api_key, "An LLM API key is required"
        assert s.elevenlabs_api_key, "ELEVENLABS_API_KEY is required"
        assert s.jwt_secret != "dev-jwt-secret-change-me", "JWT_SECRET must be rotated"
        assert s.redis_url, "REDIS_URL is required in production"
        assert not s.database_url.startswith("sqlite"), "SQLite is not supported in production"
```

If any assertion fails, the app refuses to start and logs which config is missing.

**Verification**: Start the app with `ENVIRONMENT=production` but `DEEPGRAM_API_KEY` unset. The app must exit with a clear error message, not start silently.

---

### 14.2 🟡 IMPORTANT — Set `LOG_JSON=true` and `LOG_LEVEL=WARNING` in production

**Risk**: `log_json=True` is the default but needs to be confirmed. JSON-structured logs are required for log aggregation services (Datadog, CloudWatch, Splunk). `log_level=INFO` in production generates very high log volume from the `request_complete` middleware entries.

**Fix**: Set `LOG_LEVEL=WARNING` in production (or `INFO` if you have log sampling enabled downstream). Confirm `LOG_JSON=true`.

**Verification**: Make a health check request. Confirm the log output is valid JSON. Confirm `DEBUG` level logs are not emitted.

---

### 14.3 🟡 IMPORTANT — Configure alerting for STT/LLM/TTS error rates

**Risk**: If Deepgram, OpenAI, or ElevenLabs starts returning errors (outage, rate limit, invalid API key rotation), sessions fail silently without any alert.

**Fix**: Export a metric `provider_error_count` labeled by `{provider, error_type}`. Alert if the 5-minute error rate exceeds 5% for any provider.

**Verification**: Mock Deepgram to return errors for 10 consecutive calls. Confirm an alert fires within 5 minutes.

---

### 14.4 🟡 IMPORTANT — Add a health check that validates database and Redis connectivity

**Risk**: The existing `/health` endpoint returns `{"status": "ok"}` unconditionally. If the database or Redis is down, the health check still passes, which means load balancers keep sending traffic to a broken instance.

**Fix**: Expand `/health` to include a quick DB ping and Redis ping:

```python
@app.get("/health")
async def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as e:
        return JSONResponse({"status": "degraded", "db": str(e)}, status_code=503)
    return {"status": "ok"}
```

**Verification**: Stop PostgreSQL. `GET /health` must return HTTP 503. Restart PostgreSQL. `GET /health` must return HTTP 200 within 30 seconds.

---

### 14.5 🟡 IMPORTANT — Track WebSocket session duration and turn latency as metrics

**Risk**: The latency fixes (remove `first_audio_started.wait()`, `run_in_executor` for ledger) were validated in development. In production, regressing changes may reintroduce latency. Without continuous monitoring, you won't know until users complain.

**Fix**: Emit latency metrics for:
- Time from `client.audio.chunk` received to `server.stt.transcript` emitted (STT latency)
- Time from STT transcript to first TTS audio chunk sent (LLM + TTS latency)
- Time from STT transcript to `server.turn.complete` (total turn latency)

Alert if p95 STT latency exceeds 2 seconds or p95 total turn latency exceeds 8 seconds.

**Verification**: Run `stress_test.py --turns 4` and confirm all three latency metrics are being recorded.

---

### 14.6 🟢 NICE-TO-HAVE — Add distributed tracing (OpenTelemetry) across WebSocket, DB, and provider calls

**Risk**: Without tracing, diagnosing a latency spike in production requires grepping logs across multiple services. OpenTelemetry with Jaeger or Zipkin would let you trace a single drill session from WebSocket connect to session close across all hops.

---

## 15. Performance Validation

### 15.1 🔴 BLOCKER — Run the full stress test against real providers before go-live

**Risk**: All prior testing used mock providers. Real Deepgram, OpenAI, and ElevenLabs add network RTT and processing time that mocks do not simulate.

**Fix**: Run the following sequence against the production-equivalent environment:

```bash
# Step 1: Validate Deepgram session lifecycle
python debug_deepgram_session.py

# Step 2: Stress test with TTS disabled to isolate STT + LLM
python stress_test.py --turns 4 --skip-tts

# Step 3: Full end-to-end with all providers
python stress_test.py --turns 4

# Step 4: Concurrent sessions
python stress_test.py --turns 4 --concurrent 3
```

**Acceptance criteria**:
- `debug_deepgram_session.py`: all transcripts returned within 2s of audio upload
- `--skip-tts --turns 4`: average turn latency < 4s, no `database is locked` errors
- `--turns 4` (full): average total turn latency < 8s
- `--concurrent 3`: no session crashes, no missing session artifacts

**Verification**: All four scripts pass. Share the timing output as part of the release sign-off.

---

### 15.2 🟡 IMPORTANT — Validate `flush_buffered_events` does not block under event burst

**Risk**: `run_in_executor` offloads the sync DB work to the default thread pool (size: `min(32, os.cpu_count() + 4)`). Under a burst of 200 simultaneous event flushes (e.g., many sessions ending at once), the thread pool saturates and `run_in_executor` calls queue up.

**Fix**: In `flush_buffered_events`, catch `asyncio.TimeoutError` around the executor call with a 5-second timeout. If the executor is full, log a warning and return 0 (events remain in buffer).

**Verification**: Submit 50 concurrent `flush_buffered_events` calls. Confirm none raise `asyncio.TimeoutError` under normal load, and all complete within 10 seconds.

---

### 15.3 🟡 IMPORTANT — Measure analytics endpoint performance under real data volumes

**Risk**: `management_analytics_warn_ms=800` and `management_analytics_critical_ms=1500` suggest analytics queries can be slow. With months of session data, these queries could slow further.

**Fix**: Load the staging database with 6 months of simulated session data (estimate: 10 reps × 5 sessions/day × 180 days = 9,000 sessions). Run the manager analytics endpoint and confirm p95 latency is under 800ms.

**Verification**: Analytics endpoint returns within 800ms for an org with 9,000 sessions.

---

## 16. Test Coverage Verification

### 16.1 🔴 BLOCKER — Run the full test suite and confirm zero failures before deploying

**Fix**: From the `backend/` directory:
```bash
pip install -e ".[test]"
pytest tests/ -v --tb=short 2>&1 | tee test_results.txt
grep -E "FAILED|ERROR" test_results.txt
```

All tests must pass. Zero `FAILED` or `ERROR` lines.

**Verification**: `test_results.txt` shows `X passed, 0 failed, 0 errors`.

---

### 16.2 🟡 IMPORTANT — Confirm the three new test files from Codex prompts are present and passing

**Fix**: Verify these files exist and pass:
```bash
ls tests/test_deepgram_stt_client.py
ls tests/test_ledger_flush_executor.py
ls tests/test_tts_pipeline_isolation.py
pytest tests/test_deepgram_stt_client.py tests/test_ledger_flush_executor.py tests/test_tts_pipeline_isolation.py -v
```

**Verification**: All three files exist. All tests in all three files pass.

---

### 16.3 🟡 IMPORTANT — Run mobile Jest tests

**Fix**: From the `mobile/` directory:
```bash
npm install
npx jest --testPathPattern "audio.test" --verbose
```

All 11 audio tests must pass (3 codec tests + 6 VAD hysteresis tests + 2 audio mode tests).

**Verification**: Zero Jest test failures.

---

### 16.4 🟡 IMPORTANT — Check test coverage for `ws.py` critical paths

**Risk**: `ws.py` is the most complex file in the codebase and the source of both major bugs fixed in this sprint. Confirm that the critical paths (auth failure, WebSocket disconnect mid-session, LLM error recovery, keepalive timeout) are all covered by tests.

**Fix**:
```bash
pytest tests/ --cov=app/voice/ws --cov-report=term-missing
```

Target: ≥ 70% line coverage for `ws.py`.

**Verification**: Coverage report shows ≥ 70% for `app/voice/ws.py`.

---

## 17. Data Integrity & Privacy

### 17.1 🟡 IMPORTANT — Confirm session audio payloads are never persisted to the database

**Risk**: `AudioChunk.payload` is a base64-encoded WAV file. If any code path (e.g., a debugging shortcut, a test that became production code) stores the audio payload in `SessionEvent.payload` or any other DB field, raw audio is accumulating in the database, creating a data retention and privacy liability.

**Fix**: Grep for `payload` storage in any event or turn commit:
```bash
grep -r "AudioChunk\|audio.chunk\|payload.*base64\|payload.*wav" backend/app/ --include="*.py"
```

Confirm audio payloads are only passed to Deepgram and immediately discarded. They must not appear in any `SessionEvent`, `SessionTurn`, or `SessionArtifact` record.

**Verification**: After a drill session, query the database: `SELECT payload FROM session_events LIMIT 10`. Confirm no payloads contain base64-encoded audio (strings > 1KB in the payload field are suspicious).

---

### 17.2 🟡 IMPORTANT — Add data retention policy and implement session data deletion

**Risk**: Session transcripts, turn text, and event logs accumulate indefinitely. If a user requests deletion of their data (GDPR/CCPA right to erasure), there is no mechanism to delete their sessions.

**Fix**: Implement a `DELETE /admin/users/{user_id}/data` endpoint that deletes all `SessionTurn`, `SessionEvent`, and `SessionArtifact` records for sessions belonging to that user, and removes their `User` record. Add a configurable session retention policy (e.g., delete sessions older than 365 days).

**Verification**: Call the deletion endpoint for a test user. Confirm all associated records are removed. Confirm the user cannot log in.

---

### 17.3 🟡 IMPORTANT — Ensure presigned URLs for session artifacts expire before sharing links externally

**Risk**: `default_presign_ttl_seconds=3600`. If a manager copies a presigned URL for a transcript and pastes it in a public channel, the URL is accessible for up to 1 hour. Consider reducing TTL for sensitive transcript artifacts.

**Verification**: Generate a presigned URL. Wait until expiry + 60s. Confirm the URL returns HTTP 403 (expired signature).

---

## 18. Deployment & Rollback

### 18.1 🔴 BLOCKER — Document and test the rollback procedure before go-live

**Risk**: If a production deployment causes a critical regression, you need to be able to roll back within minutes.

**Fix**: Document the rollback procedure:
1. Revert the container image to the previous tag: `docker pull doordrill:previous && docker stop doordrill && docker run doordrill:previous`
2. If a database migration was applied, run `alembic downgrade -1` to reverse it
3. Flush all in-flight Redis events before restarting to avoid processing events with the old schema

**Verification**: Perform a rollback drill in staging. Time it. Target: < 5 minutes from decision to rollback to traffic fully restored on the previous version.

---

### 18.2 🟡 IMPORTANT — Tag every production deployment with a version

**Risk**: Without versioned deployments, you cannot confidently say "we rolled back to version X" because you don't know what version X contains.

**Fix**: Tag each production release:
```bash
git tag v1.0.0-prod-$(date +%Y%m%d) && git push --tags
```

Include the git SHA in the `GET /health` response: `{"status": "ok", "sha": "<git-sha>"}`.

**Verification**: `GET /health` returns a `sha` field that matches the deployed git commit.

---

### 18.3 🟡 IMPORTANT — Use a blue/green or canary deployment for the initial launch

**Risk**: Deploying directly to all traffic on the first production release is high-risk. A bug that only manifests under real user behavior could affect all users simultaneously.

**Fix**: Deploy the new version to a `staging` stack and send 5% of production traffic to it for 24 hours. Monitor error rates and latency. If healthy, promote to 100%.

**Verification**: Traffic split is confirmed via load balancer configuration. Staging receives real user traffic for 24 hours with no critical errors.

---

## 19. Third-Party Provider Hardening

### 19.1 🟡 IMPORTANT — Set Deepgram connection timeout at the WebSocket transport level

**Risk**: `websockets.connect()` for Deepgram has no `open_timeout` parameter set. The default is `None` (wait forever). Under a partial Deepgram outage (TCP connects but handshake stalls), the connection hangs indefinitely.

**Fix**: Pass `open_timeout=10` to `websockets.connect()` in `_stream_utterance`.

**Verification**: Mock the Deepgram WebSocket to stall the handshake for 15 seconds. Confirm `_stream_utterance` raises `TimeoutError` within 11 seconds.

---

### 19.2 🟡 IMPORTANT — Monitor Deepgram API key usage and quota

**Risk**: Deepgram charges per audio-second processed. Without usage monitoring, an unexpected spike (load test, bot sessions) could generate an unexpected bill.

**Fix**: Set up a Deepgram usage alert in the Deepgram dashboard for > $X/day or > Y audio-hours/day. Add a server-side counter for total Deepgram audio-seconds processed per day.

**Verification**: Deepgram dashboard has an active budget alert configured.

---

### 19.3 🟡 IMPORTANT — Validate ElevenLabs character quota

**Risk**: ElevenLabs charges per character synthesized. A highly active production deployment can exhaust monthly character quotas. Without a guard, TTS calls will start returning 429s mid-session with no warning.

**Fix**: Track total ElevenLabs characters synthesized per session and per day. Alert at 80% of monthly quota.

**Verification**: ElevenLabs dashboard usage alert is configured. Server-side character counter is emitted as a metric.

---

### 19.4 🟡 IMPORTANT — Implement circuit breakers for all three provider clients

**Risk**: If Deepgram, OpenAI, or ElevenLabs has an outage, the app currently retries indefinitely, blocking event loop capacity. A circuit breaker pattern (open after 5 consecutive failures, half-open after 30 seconds) prevents retry storms.

**Verification**: Simulate a Deepgram outage (block outbound connections to `api.deepgram.com`). After 5 consecutive failures, new STT requests must be rejected immediately with a `stt.circuit_open` error event rather than waiting for timeout.

---

## 20. Pre-Launch Smoke Test Protocol

Run this protocol end-to-end on the production environment with real credentials before opening to users. Each step must complete successfully before proceeding to the next.

### Step 1 — Infrastructure Health
- [ ] `GET /health` returns HTTP 200 `{"status": "ok"}`
- [ ] Health check includes DB and Redis ping, both passing
- [ ] Startup log shows all required config is set (`validate_production_config` passes)
- [ ] No `ENVIRONMENT=dev` in any production process

### Step 2 — Authentication
- [ ] `POST /auth/login` with valid credentials returns HTTP 200 and `access_token`
- [ ] `POST /auth/login` with invalid credentials returns HTTP 401
- [ ] Unauthenticated `GET /api/rep/sessions` returns HTTP 401
- [ ] Expired JWT returns HTTP 401
- [ ] Valid JWT returns correct user data

### Step 3 — Database
- [ ] `alembic current` shows migration `0031` with no pending migrations
- [ ] `alembic history` shows all 31 migrations applied
- [ ] `EXPLAIN ANALYZE` on key queries shows `Index Scan`, not `Seq Scan`

### Step 4 — WebSocket Voice Session (Manual)
- [ ] Open WebSocket connection with valid JWT — connection accepted
- [ ] Open WebSocket connection without JWT — connection rejected (4001)
- [ ] `server.session.ready` event received within 3 seconds
- [ ] `server.session.rag_context_loaded` received if RAG documents are present for the org
- [ ] Send 2 seconds of 16kHz mono WAV silence — no server crash
- [ ] Send 2 seconds of 16kHz mono WAV with speech — `server.stt.transcript` received within 2 seconds
- [ ] `server.homeowner.turn.start` and `server.homeowner.audio.chunk` received within 5 seconds of transcript
- [ ] `server.turn.complete` received after homeowner finishes speaking
- [ ] `client.session.end` gracefully closes session — `server.session.summary` received
- [ ] `DrillSession` record in DB has `status=COMPLETED` and non-null `ended_at`
- [ ] `SessionArtifact` with `artifact_type=canonical_transcript` exists in DB
- [ ] Transcript JSON is retrievable from object storage via presigned URL

### Step 5 — STT Codec Validation
- [ ] Confirm WAV audio produces `server.stt.transcript` within 2s (not 12–15s)
- [ ] Confirm Deepgram `_listen_url` logs show `encoding=linear16`, no `mimetype` for WAV audio
- [ ] Confirm `start_session` does NOT appear in Deepgram WebSocket open logs until first audio

### Step 6 — Ledger Flush Validation
- [ ] Send 50 events in rapid succession — all 50 appear in `session_events` table after session ends
- [ ] Confirm `flush_buffered_events` log shows `run_in_executor` completion, not a sync block

### Step 7 — Mobile App Validation (on physical device)
- [ ] Microphone permission dialog appears on first launch
- [ ] Hold mic button → VAD indicator activates after ~160ms of speech (2 attack frames × 80ms)
- [ ] Release mic button → audio chunk sent to server
- [ ] Server returns homeowner TTS audio within 8 seconds
- [ ] TTS audio plays without stutter between chunks
- [ ] Confirm iOS AVFoundation logs show one `setMode` call per audio drain cycle, not per chunk

### Step 8 — Load Test
- [ ] `python stress_test.py --turns 4` completes with all turns < 8s average latency
- [ ] `python stress_test.py --turns 4 --concurrent 3` completes with no session crashes
- [ ] No `database is locked` or `QueuePool limit` errors in logs

### Step 9 — Security Scan
- [ ] `git log --all -p | grep -E 'API_KEY|SECRET|PASSWORD'` — no keys in history
- [ ] `GET /docs` returns HTTP 404 in production
- [ ] `GET /health` does not expose stack traces
- [ ] Unauthenticated WebSocket connect is rejected with 4001/4003

### Step 10 — Rollback Drill
- [ ] Rollback to previous version completes in < 5 minutes
- [ ] `GET /health` returns 200 on rolled-back version
- [ ] All smoke test steps 1–3 pass on rolled-back version

---

## Final Sign-off

| Category | Owner | Status | Date |
|---|---|---|---|
| Security & Auth | | ☐ | |
| Database & Migrations | | ☐ | |
| WebSocket & Voice Pipeline | | ☐ | |
| STT Pipeline | | ☐ | |
| LLM Pipeline | | ☐ | |
| TTS Pipeline | | ☐ | |
| Storage & Artifacts | | ☐ | |
| Redis & Event Buffer | | ☐ | |
| Mobile App | | ☐ | |
| Infrastructure | | ☐ | |
| CORS & Network | | ☐ | |
| Rate Limiting | | ☐ | |
| Error Handling | | ☐ | |
| Observability | | ☐ | |
| Performance | | ☐ | |
| Test Coverage | | ☐ | |
| Data Integrity | | ☐ | |
| Deployment & Rollback | | ☐ | |
| Provider Hardening | | ☐ | |
| Smoke Test Protocol | | ☐ | |

**Deployment approved**: __________________ Date: __________

> All 🔴 BLOCKER items must be signed off before any production traffic is allowed. 🟡 IMPORTANT items should be completed within the first two weeks post-launch. 🟢 NICE-TO-HAVE items can be scheduled as backlog.
