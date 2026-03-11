# DoorDrill — Production Checklist Codex Prompts

Organized into **4 batches**. Within each batch, all prompts are independent and can be pasted into simultaneous Codex agents. Wait for a batch to finish before starting the next — later batches depend on changes made by earlier ones.

---

## BATCH 1 — Core infrastructure (run all 5 simultaneously)

---

### Prompt 1-A: `main.py` + `config.py` — Docs lockdown, CORS config, startup validator, health check

```
You are working in the backend of a FastAPI application called DoorDrill.

Make the following changes:

---

FILE: backend/app/core/config.py

Add a new field to the `Settings` class:

    cors_origins: list[str] = Field(
        default=["http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:4173", "http://127.0.0.1:4173"],
        alias="CORS_ORIGINS",
    )

---

FILE: backend/app/main.py

1. Replace the hardcoded CORS `allow_origins` list with `settings.cors_origins`.

2. Replace `allow_methods=["*"]` with `allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]`.

3. Replace `allow_headers=["*"]` with `allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Trace-Id"]`.

4. Disable FastAPI docs when `settings.environment == "production"` by changing the `FastAPI(...)` constructor call to:

    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
        lifespan=lifespan,
    )

5. Add a `validate_production_config` function and call it inside the `lifespan` context manager before `yield`:

    def validate_production_config() -> None:
        s = get_settings()
        if s.environment != "production":
            return
        errors = []
        if s.stt_provider == "mock":
            errors.append("STT_PROVIDER must not be 'mock' in production")
        if s.llm_provider == "mock":
            errors.append("LLM_PROVIDER must not be 'mock' in production")
        if s.tts_provider == "mock":
            errors.append("TTS_PROVIDER must not be 'mock' in production")
        if not s.deepgram_api_key:
            errors.append("DEEPGRAM_API_KEY is required")
        if not s.openai_api_key and not s.anthropic_api_key:
            errors.append("At least one LLM API key (OPENAI_API_KEY or ANTHROPIC_API_KEY) is required")
        if not s.elevenlabs_api_key:
            errors.append("ELEVENLABS_API_KEY is required")
        if s.jwt_secret == "dev-jwt-secret-change-me":
            errors.append("JWT_SECRET must be changed from the default dev value")
        if not s.redis_url:
            errors.append("REDIS_URL is required in production")
        if s.database_url.startswith("sqlite"):
            errors.append("SQLite is not supported in production; set DATABASE_URL to a PostgreSQL URL")
        if errors:
            for err in errors:
                logging.getLogger("doordrill.startup").error("config_validation_error", extra={"error": err})
            raise RuntimeError(f"Production config validation failed: {'; '.join(errors)}")

6. Replace the existing simple `GET /health` endpoint with a richer one that pings the database and Redis:

    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    @app.get("/health")
    async def health() -> JSONResponse:
        import importlib
        checks: dict[str, str] = {}
        # Database ping
        try:
            from app.db.session import SessionLocal
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as exc:
            checks["db"] = str(exc)
        # Redis ping (optional — only if REDIS_URL is set)
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis
                r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
                await r.ping()
                await r.aclose()
                checks["redis"] = "ok"
            except Exception as exc:
                checks["redis"] = str(exc)
        status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        code = 200 if status == "ok" else 503
        import subprocess, contextlib
        sha = ""
        with contextlib.suppress(Exception):
            sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        return JSONResponse({"status": status, "checks": checks, "sha": sha}, status_code=code)

Preserve all existing imports and routes. Do not remove the static files mount.
```

---

### Prompt 1-B: `app/db/session.py` — Production connection pool

```
You are working in the backend of a FastAPI application called DoorDrill.

FILE: backend/app/db/session.py

Make the following changes:

1. Replace the `create_engine(...)` call with a version that includes explicit production-grade pool settings and separates the SQLite vs PostgreSQL connect_args cleanly:

    is_sqlite = settings.database_url.startswith("sqlite")
    connect_args: dict = {}
    if is_sqlite:
        connect_args = {"check_same_thread": False}
    else:
        connect_args = {"sslmode": "require"}

    engine = create_engine(
        settings.database_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=10 if not is_sqlite else 1,
        max_overflow=20 if not is_sqlite else 0,
        pool_timeout=30,
        pool_recycle=1800,
        connect_args=connect_args,
    )

2. Do not change anything else. Preserve `SessionLocal`, `get_db`, and all imports.
```

---

### Prompt 1-C: New Alembic migration — Missing production indexes

```
You are working in the backend of a FastAPI application called DoorDrill.

Create a new Alembic migration file at:
  backend/alembic/versions/20260310_0032_production_indexes.py

The migration should add the following indexes if they do not already exist. Use `op.create_index` with `if_not_exists=True` for safety.

Indexes to add:
1. On `session_events` table: a unique index on `event_id` column.
   Name: `ix_session_events_event_id_unique`
   Unique: True

2. On `session_turns` table: a composite index on `(session_id, turn_index)`.
   Name: `ix_session_turns_session_turn_idx`

3. On `assignments` table: a composite index on `(rep_id, status)`.
   Name: `ix_assignments_rep_status`

The downgrade function must drop all three indexes.

Set the migration's `down_revision` to the most recent migration revision ID found in `backend/alembic/versions/`. Scan the existing version files to find the correct ID rather than hardcoding a guess.

Use standard Alembic op functions. Do not use raw SQL. Do not import any app models.
```

---

### Prompt 1-D: `provider_clients.py` — Deepgram hardening

```
You are working in the backend of a FastAPI application called DoorDrill.

FILE: backend/app/services/provider_clients.py

Make the following changes to the `DeepgramSTTClient` class:

1. In `_stream_utterance`, the `websockets.connect()` call already passes `open_timeout=self.timeout_seconds`. Confirm this is present. If it is not, add `open_timeout=self.timeout_seconds` as a keyword argument.

2. Increase the maximum retry count on `ConnectionClosed` from 1 retry to 2 retries:
   - The current logic uses a boolean `retried` flag. Replace it with an integer `retry_count = 0` and a constant `MAX_RETRIES = 2`.
   - Change `if retried: raise` to `if retry_count >= MAX_RETRIES: raise`.
   - Change `retried = True` (both occurrences) to `retry_count += 1`.
   - After incrementing `retry_count`, add an exponential backoff sleep before retrying:
     `await asyncio.sleep(min(0.5 * retry_count, 1.0))`

3. In `_listen_url`, add `"utterance_end_ms": "1000"` to the `params` dict alongside the other default params (`smart_format`, `punctuate`, etc.).

4. Do not change anything else. Preserve `start_session`, `end_session`, the codec routing logic in `_listen_url`, and all other methods.
```

---

### Prompt 1-E: `ledger_service.py` — OperationalError resilience

```
You are working in the backend of a FastAPI application called DoorDrill.

FILE: backend/app/services/ledger_service.py

Make the following changes to the `SessionLedgerService` class:

1. Import `OperationalError` from SQLAlchemy at the top of the file:
   `from sqlalchemy.exc import OperationalError`

2. In `_flush_sync`, wrap the entire method body (everything after `worker_db = SessionLocal()`) in a `try/except OperationalError` block. On `OperationalError`:
   - Log a warning with the message `"ledger_flush_db_error"` including the exception text and the number of events that were not flushed.
   - Return `0` (do not re-raise).
   - The `finally:` block that closes `worker_db` must still run.

3. In `flush_buffered_events`, add a `try/except Exception` around the entire executor/shield block. On any unexpected exception:
   - Log a warning with `"ledger_flush_unexpected_error"`.
   - Return `0` (do not re-raise — the session loop must not crash due to a flush failure).

4. Do not change any other methods. Preserve `buffer_event`, `commit_turn`, `compact_session`, and `_parse_iso`.
```

---

## BATCH 2 — WebSocket hardening (run all 3 simultaneously, after Batch 1)

---

### Prompt 2-A: `ws.py` — Auth, RBAC, Origin check, concurrent session limit, standard error events, session cleanup

```
You are working in the backend of a FastAPI application called DoorDrill.

FILE: backend/app/voice/ws.py

Make the following changes. Read the file carefully first — do not remove any existing logic.

---

CHANGE 1: Origin header validation

At the top of the `session_ws` handler (before `await websocket.accept()`), add an Origin check:

    from app.core.config import get_settings as _get_settings
    _s = _get_settings()
    origin = websocket.headers.get("origin", "")
    allowed = _s.cors_origins  # list[str] from Settings
    if origin and allowed and not any(origin.startswith(o) for o in allowed):
        await websocket.close(code=4003, reason="Origin not allowed")
        return

---

CHANGE 2: Concurrent session limit per user

Add a module-level dict to track open sessions per user:

    _active_sessions_by_user: dict[str, set[str]] = {}

After the actor is resolved and the session_id is known, register the session:

    uid = actor.user_id or "anon"
    _active_sessions_by_user.setdefault(uid, set())
    if len(_active_sessions_by_user[uid]) >= 2:
        await websocket.close(code=4029, reason="Too many concurrent sessions")
        return
    _active_sessions_by_user[uid].add(session_id)

In the `finally:` block of the handler (where session cleanup happens), remove the session:

    _active_sessions_by_user.get(uid, set()).discard(session_id)

---

CHANGE 3: RBAC check on `client.session.end`

In the `receive_loop` where `msg.type == "client.session.end"` is handled, before processing the end event, add an ownership check:

    if actor.user_id and session.rep_id and session.rep_id != actor.user_id and actor.role not in {"manager", "admin"}:
        await emit_error("forbidden", "You do not own this session", retryable=False)
        continue

---

CHANGE 4: Standard `emit_error` function

The existing `emit_error` function at line ~277 already emits a `server.error` event. Confirm it includes `"retryable"` and `"code"` fields in the payload. If the current implementation does not include both fields, update it to match this signature:

    async def emit_error(code: str, message: str, *, retryable: bool = True, details: dict[str, Any] | None = None) -> None:
        await emit_server_event("server.error", {
            "code": code,
            "message": message,
            "retryable": retryable,
            **({"details": details} if details else {}),
        })

---

CHANGE 5: Emit `server.error` on provider failures

In `run_stt` (around line 309), where STT errors are currently handled, add an `emit_error` call on exception:

    except Exception as exc:
        logger.exception("stt_error", extra={"session_id": session_id})
        await emit_error("stt_error", "Speech recognition failed", retryable=True)

In `stream_ai_response`, where LLM streaming errors are caught, similarly add:

    except Exception as exc:
        logger.exception("llm_error", extra={"session_id": session_id})
        await emit_error("llm_error", "AI response failed", retryable=True)

In `stream_tts_for_plan`, where TTS errors are caught, add:

    except Exception as exc:
        logger.exception("tts_error", extra={"session_id": session_id})
        await emit_error("tts_error", "Text-to-speech failed", retryable=True)

---

CHANGE 6: LLM rate limit retry

In `stream_ai_response`, wrap the `async for token in providers.llm.stream_reply(...)` call with retry logic for rate limit errors:

    from openai import RateLimitError as OpenAIRateLimitError
    import anthropic as _anthropic

    for _attempt in range(3):
        try:
            async for token in providers.llm.stream_reply(...):
                ...
            break
        except (OpenAIRateLimitError, _anthropic.RateLimitError):
            if _attempt == 2:
                raise
            await asyncio.sleep(2 ** _attempt)

Wrap the import in a `try/except ImportError` so missing packages don't break the module.

---

CHANGE 7: Session cleanup in finally block

In the outermost `finally:` block of `session_ws` (around line 1043+), confirm that the following calls exist. If any are missing, add them:

    await providers.stt.end_session(session_id)

Confirm the DB session's `DrillSession.status` is set to a terminal value (`COMPLETED`, `ABANDONED`, etc.) and `ended_at` is set if it hasn't been already.

---

Do not change any other logic. Preserve `homeowner_token_budget`, `_dedupe_retrieved_chunks`, `stream_tts_for_plan`, `tts_emit_lock`, `maybe_flush`, `keepalive_loop`, RAG retrieval, and all event emission helpers.
```

---

### Prompt 2-B: `app/api/auth.py` — Rate limiting on login, register, and refresh

```
You are working in the backend of a FastAPI application called DoorDrill.

Install the `slowapi` package. Add rate limiting to the auth endpoints.

---

STEP 1: Add slowapi to pyproject.toml / requirements

Add `slowapi>=0.1.9` to the project's dependency list (check pyproject.toml or requirements.txt to determine which format is used).

---

STEP 2: Configure the limiter in a shared module

Create (or add to) `backend/app/core/rate_limit.py`:

    from slowapi import Limiter
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)

---

STEP 3: Register the limiter on the FastAPI app

In `backend/app/main.py`, after `app = FastAPI(...)`:

    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from app.core.rate_limit import limiter

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

---

STEP 4: Apply rate limits to auth routes

In `backend/app/api/auth.py`:

Import:
    from fastapi import Request
    from app.core.rate_limit import limiter

Add the `@limiter.limit(...)` decorator to these endpoints. The decorator must be placed immediately before the `@router.post(...)` decorator (order matters for slowapi):

- `POST /login`: `@limiter.limit("10/minute")`
- `POST /register`: `@limiter.limit("5/minute")`
- `POST /refresh`: `@limiter.limit("20/minute")`
- `POST /accept-invite`: `@limiter.limit("5/minute")`

For each decorated endpoint, add `request: Request` as the first parameter if it is not already present.

---

Do not change any business logic in the auth endpoints. Preserve all existing imports and DB operations.
```

---

### Prompt 2-C: `app/services/ledger_buffer.py` — Atomic Redis drain + configurable TTL

```
You are working in the backend of a FastAPI application called DoorDrill.

FILE: backend/app/services/ledger_buffer.py

Make the following changes to `RedisEventBuffer`:

---

CHANGE 1: Make TTL configurable with a longer default

Change the `__init__` signature to:

    def __init__(self, redis_url: str, ttl_seconds: int = 3600) -> None:

(Was 1200. 3600 = 1 hour, accommodating reps who pause and return.)

---

CHANGE 2: Atomic drain using a Lua script

Replace the existing `drain` method body with an atomic Lua-script-based pop. This prevents double-draining under concurrent multi-worker deployments.

    async def drain(self, session_id: str, max_n: int) -> list[dict[str, Any]]:
        key = self._key(session_id)
        lua_script = """
        local key = KEYS[1]
        local n = tonumber(ARGV[1])
        local items = redis.call('LRANGE', key, 0, n - 1)
        if #items > 0 then
            redis.call('LTRIM', key, n, -1)
        end
        return items
        """
        raw_items = await self._redis.eval(lua_script, 1, key, max_n)
        if not raw_items:
            return []
        return [json.loads(item) for item in raw_items]

Make sure `json` is imported at the top of the file if it isn't already.

---

CHANGE 3: Update `ws.py` call site (if applicable)

In `backend/app/voice/ws.py`, the `RedisEventBuffer` is constructed at module level:

    event_buffer = RedisEventBuffer(settings.redis_url) if settings.redis_url else InMemoryEventBuffer()

No change needed here — the default TTL is already updated in the class.

---

Do not change `push`, `InMemoryEventBuffer`, or `BaseEventBuffer`.
```

---

## BATCH 3 — Mobile + storage hardening (run all 2 simultaneously, after Batch 1)

---

### Prompt 3-A: Mobile — Permission error UI, app version header, offline detection

```
You are working in the mobile React Native / Expo codebase for DoorDrill.

---

FILE: mobile/src/services/audio.ts

CHANGE 1: Surface permission errors more clearly

In `ensurePermission()`, the current error thrown is:
  `throw new Error("Microphone permission is required to run live drills")`

Add a custom error class before the `AudioCaptureService` class definition:

    export class MicrophonePermissionError extends Error {
      readonly code = "MICROPHONE_PERMISSION_DENIED";
      constructor() {
        super("Microphone permission is required to run live drills");
        this.name = "MicrophonePermissionError";
      }
    }

Replace the `throw new Error(...)` in `ensurePermission` with `throw new MicrophonePermissionError()`.

---

FILE: mobile/src/screens/SessionScreen.tsx (or wherever `audioService.start()` is called)

CHANGE 2: Catch permission error and show alert

Wrap the `audioService.start()` call (and any call site that can throw `MicrophonePermissionError`) in a try/catch:

    import { MicrophonePermissionError } from "../services/audio";
    import { Alert } from "react-native";

    try {
      await audioService.start();
    } catch (err) {
      if (err instanceof MicrophonePermissionError) {
        Alert.alert(
          "Microphone Access Required",
          "Please enable microphone access in your device settings to use live drills.",
          [{ text: "OK" }]
        );
        return;
      }
      throw err;
    }

---

FILE: mobile/src/services/audio.ts (or the WebSocket connection service)

CHANGE 3: Add app version header to WebSocket connection

In the file where the WebSocket connection to the backend is opened (look for `new WebSocket(...)` or the URL construction), add an app version subprotocol or query param:

    import Constants from "expo-constants";
    const appVersion = Constants.expoConfig?.version ?? "unknown";

    // Append to the WebSocket URL as a query param:
    const wsUrl = `${baseUrl}/ws/voice/${sessionId}?app_version=${encodeURIComponent(appVersion)}`;

If the WebSocket URL is constructed differently, adapt accordingly. The goal is that the server receives an app version string per connection.

---

CHANGE 4: Offline detection before connecting

In the component or hook that initiates the drill session (before opening the WebSocket), add a network check using expo-network or the NetInfo API:

    import NetInfo from "@react-native-community/netinfo";

    const netState = await NetInfo.fetch();
    if (!netState.isConnected) {
      Alert.alert(
        "No Internet Connection",
        "Please check your connection and try again.",
        [{ text: "OK" }]
      );
      return;
    }

If `@react-native-community/netinfo` is not installed, add it to `package.json` dependencies and run `npx expo install @react-native-community/netinfo`.

---

Do not change RECORDING_OPTIONS, VAD logic, stop(), handleStatus(), or any other audio capture logic.
```

---

### Prompt 3-B: `ledger_service.py` + `ws.py` — Graceful shutdown drain

```
You are working in the backend of a FastAPI application called DoorDrill.

The goal is to ensure buffered ledger events are not lost when the server shuts down (SIGTERM during a rolling deployment).

---

FILE: backend/app/main.py

In the `lifespan` async context manager, add a shutdown drain after the `yield`:

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        validate_production_config()
        init_db()
        yield
        # Shutdown: flush any remaining in-memory events
        # (Redis-backed events survive process restart; this guards InMemoryEventBuffer)
        from app.voice.ws import ledger, event_buffer
        from app.services.ledger_buffer import InMemoryEventBuffer
        if isinstance(event_buffer, InMemoryEventBuffer):
            logger.info("shutdown_drain_start")
            from app.db.session import SessionLocal
            with SessionLocal() as db:
                # Drain all sessions present in the buffer
                for session_id in list(getattr(event_buffer, "_store", {}).keys()):
                    try:
                        await ledger.flush_buffered_events(db, session_id, max_n=10000)
                    except Exception:
                        logger.exception("shutdown_drain_error", extra={"session_id": session_id})
            logger.info("shutdown_drain_complete")

Note: `InMemoryEventBuffer` stores data in a `_store` dict keyed by `session_id`. Verify this matches the actual attribute name in `ledger_buffer.py` before implementing — adjust if different.

---

Do not change any other part of lifespan. Preserve `init_db()`, logging setup, and all routers.
```

---

## BATCH 4 — Upload validation + `.gitignore` hygiene (run both simultaneously, after Batch 1)

---

### Prompt 4-A: Upload size enforcement

```
You are working in the backend of a FastAPI application called DoorDrill.

Search for all file upload endpoints in `backend/app/api/`. These are endpoints that accept `UploadFile` from FastAPI.

For each upload endpoint found, add a file size check immediately after the file parameter is received:

    from app.core.config import get_settings as _cfg
    contents = await file.read()
    if len(contents) > _cfg().max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_cfg().max_upload_size_bytes // 1_048_576}MB.",
        )
    # Then pass `contents` to whatever processes the file, rather than re-reading from `file`

If the endpoint already reads the file into memory for processing, integrate the size check before the processing step rather than reading twice.

Do not change endpoints that do not accept file uploads. Do not change business logic.
```

---

### Prompt 4-B: `.gitignore` — Remove SQLite files from tracking

```
You are working in the DoorDrill repository root.

TASK 1: Update .gitignore

Add the following lines to the root `.gitignore` file if they are not already present:

    # SQLite databases (never commit these)
    *.db
    *.db-shm
    *.db-wal
    *.sqlite
    *.sqlite3

    # Local env files
    .env
    !.env.example

TASK 2: Remove tracked database files from git index

Run the following git commands to stop tracking these files without deleting them from disk:

    git rm --cached backend/doordrill.db 2>/dev/null || true
    git rm --cached backend/test_provider_clients.db 2>/dev/null || true
    git rm --cached "*.db" --ignore-unmatch 2>/dev/null || true

TASK 3: Verify

Run `git ls-files | grep "\.db$"` and confirm the output is empty.

Do not delete any .db files from disk. Only remove them from git tracking.
```

---

## Summary: Which prompts touch which files

| Prompt | Files Modified | Can run with |
|--------|---------------|--------------|
| 1-A | `main.py`, `config.py` | 1-B, 1-C, 1-D, 1-E, 3-A, 3-B, 4-A, 4-B |
| 1-B | `db/session.py` | All of Batch 1 |
| 1-C | New alembic migration | All of Batch 1 |
| 1-D | `provider_clients.py` | All of Batch 1 |
| 1-E | `ledger_service.py` | All of Batch 1, NOT 3-B (both touch ledger) |
| 2-A | `ws.py` | 2-B, 2-C |
| 2-B | `api/auth.py`, `main.py` | 2-A, 2-C — but 1-A must finish first |
| 2-C | `ledger_buffer.py` | 2-A, 2-B |
| 3-A | `audio.ts`, `SessionScreen.tsx` | 3-B, all of Batch 1 |
| 3-B | `main.py`, `ledger_service.py` | 3-A — but 1-A and 1-E must finish first |
| 4-A | `api/*.py` (upload endpoints) | All of Batch 1 |
| 4-B | `.gitignore`, git index | Everything |

## Remaining items that are NOT Codex prompts

These must be done manually or by your ops/infra team:

- Rotate `JWT_SECRET` → edit `.env` directly (never commit)
- Set `AUTH_REQUIRED=true`, `ENVIRONMENT=production` → edit `.env`
- Set `REDIS_URL`, `DATABASE_URL` (PostgreSQL), `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` → edit `.env`
- Run `alembic upgrade head` against production database
- Set Redis password in connection string (`redis://:password@host:6379/0`)
- Configure S3 bucket CORS policy via AWS console
- Set up Deepgram and ElevenLabs usage alerts in each provider's dashboard
- Switch production server to `gunicorn -k uvicorn.workers.UvicornWorker` (not `--reload`)
- Run stress tests: `python stress_test.py --turns 4` and `--concurrent 3`
- Run the Section 20 smoke test protocol manually against production
