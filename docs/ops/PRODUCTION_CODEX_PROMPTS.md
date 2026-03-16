# DoorDrill — Production Checklist Codex Prompts

Organized into **5 batches**. Within each batch, all prompts are independent and can be pasted into simultaneous Codex agents. Wait for a batch to finish before starting the next — later batches depend on changes made by earlier ones.

## Production Readiness Reference

Every Codex agent working on this codebase should treat **`backend/docs/ops/staging-prod-env-matrix.md`** as the source of truth for production requirements. Before marking any task complete, verify your change satisfies the relevant rows in the Release Readiness Gate and Observability Minimum sections of that document.

**Audit status as of 2026-03-10:**
- ✅ DONE: JWT auth (mobile + backend), invite flow, push notifications, manager dashboard, onboarding screens, DB migrations (32 total, up to date)
- ⚠️ PARTIAL: RAG infrastructure ready, zero documents uploaded; secrets in plaintext .env (acceptable locally, must not be committed)
- ❌ MISSING — addressed in Batch 5 below: Dockerfile/fly.toml, Sentry error monitoring, password reset flow

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

## BATCH 5 — Deployment, observability, and password reset (run all 3 simultaneously, after Batch 1)

---

### Prompt 5-A: Dockerfile + fly.toml — Backend deployment config

```
You are working in the DoorDrill repository. Read backend/docs/ops/staging-prod-env-matrix.md before starting — it defines the service topology and required environment variables for production.

Create the following two files exactly as specified.

---

FILE: backend/Dockerfile

    FROM python:3.12-slim

    WORKDIR /app

    # System deps for psycopg2 + build tools
    RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl git \
        && rm -rf /var/lib/apt/lists/*

    COPY pyproject.toml .
    RUN pip install --no-cache-dir -e ".[standard]" 2>/dev/null || pip install --no-cache-dir .

    COPY . .

    # Run as non-root
    RUN useradd -m appuser && chown -R appuser /app
    USER appuser

    EXPOSE 8000

    # Production: no --reload, use multiple workers
    CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

---

FILE: fly.toml (in the repo root, not backend/)

    app = "doordrill-api"
    primary_region = "iad"

    [build]
      dockerfile = "backend/Dockerfile"
      build_target = ""

    [env]
      ENVIRONMENT = "production"
      PORT = "8000"

    [http_service]
      internal_port = 8000
      force_https = true
      auto_stop_machines = "stop"
      auto_start_machines = true
      min_machines_running = 1
      processes = ["app"]

      [[http_service.checks]]
        grace_period = "10s"
        interval = "15s"
        method = "GET"
        path = "/health"
        protocol = "http"
        timeout = "5s"

    [[vm]]
      size = "shared-cpu-2x"
      memory = "1gb"

    [mounts]
      # No persistent disk needed — all state is in Supabase + Redis

After creating both files, verify:
1. backend/Dockerfile exists and has CMD with uvicorn
2. fly.toml exists at repo root with health check path /health
3. Do not commit .env or any secrets
4. Cross-reference backend/docs/ops/staging-prod-env-matrix.md — confirm every required env var listed there is documented in backend/.env.example (add any that are missing)
```

---

### Prompt 5-B: Sentry — Error monitoring for FastAPI backend

```
You are working in the backend of a FastAPI application called DoorDrill. Read backend/docs/ops/staging-prod-env-matrix.md — the Observability Minimum section defines what must be monitored in production.

Add Sentry error monitoring to the FastAPI backend.

---

STEP 1: Add dependency

Add `sentry-sdk[fastapi]>=2.0.0` to pyproject.toml dependencies.

---

STEP 2: Add SENTRY_DSN to Settings

In backend/app/core/config.py, add to the Settings class:

    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    sentry_traces_sample_rate: float = Field(default=0.1, alias="SENTRY_TRACES_SAMPLE_RATE")

---

STEP 3: Initialize Sentry in main.py

In backend/app/main.py, at the top of the file after imports, add:

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    import logging as _logging

    def _init_sentry(settings) -> None:
        if not settings.sentry_dsn:
            return
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                LoggingIntegration(
                    level=_logging.INFO,
                    event_level=_logging.ERROR,
                ),
            ],
            # Never send auth tokens or passwords to Sentry
            before_send=lambda event, hint: _scrub_sentry_event(event, hint),
        )

    def _scrub_sentry_event(event: dict, hint: dict) -> dict:
        """Strip Authorization headers and password fields from Sentry events."""
        request = event.get("request", {})
        headers = request.get("headers", {})
        if "authorization" in headers:
            headers["authorization"] = "[Filtered]"
        if "cookie" in headers:
            headers["cookie"] = "[Filtered]"
        data = request.get("data", {})
        if isinstance(data, dict):
            for key in ("password", "password_hash", "token", "refresh_token", "access_token"):
                if key in data:
                    data[key] = "[Filtered]"
        return event

Call `_init_sentry(settings)` inside the `lifespan` context manager, before `yield`, after `validate_production_config()`.

---

STEP 4: Add SENTRY_DSN to .env.example

In backend/.env.example, add:

    # Error monitoring (get DSN from sentry.io → Project Settings → Client Keys)
    SENTRY_DSN=
    SENTRY_TRACES_SAMPLE_RATE=0.1

---

STEP 5: Verify

1. When SENTRY_DSN is empty/unset, Sentry must NOT be initialized (silent skip)
2. The _scrub_sentry_event function strips Authorization headers and password fields
3. The FastAPI and SQLAlchemy integrations are registered
4. No existing tests should fail — Sentry init is a no-op when DSN is absent

Do not add Sentry to the mobile app or dashboard in this prompt.
```

---

### Prompt 5-C: Password reset flow — Backend + Mobile

```
You are working in the DoorDrill codebase. Password reset is a production blocker — users who forget their password currently have no recovery path.

Implement a full password reset flow: request → email with token → mobile screen to set new password.

---

BACKEND — backend/app/api/auth.py

Add two new endpoints.

1. POST /auth/request-password-reset

    class PasswordResetRequest(BaseModel):
        email: EmailStr

    @router.post("/request-password-reset", status_code=204)
    def request_password_reset(
        payload: PasswordResetRequest,
        db: Session = Depends(get_db),
    ) -> None:
        user = db.scalar(select(User).where(User.email == payload.email.lower()))
        # Always return 204 regardless — do not reveal whether email exists
        if user is None:
            return
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        reset = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
        )
        db.add(reset)
        db.commit()
        # Send email
        email_provider = get_email_provider()
        reset_url = f"doordrill://reset-password?token={token}"
        asyncio.get_event_loop().run_until_complete(
            email_provider.send(
                to=user.email,
                subject="Reset your DoorDrill password",
                body=f"Tap the link to reset your password (expires in 2 hours):\n\n{reset_url}\n\nIf you didn't request this, ignore this email.",
            )
        )

2. POST /auth/reset-password

    class PasswordResetConfirm(BaseModel):
        token: str
        new_password: str = Field(min_length=8)

    @router.post("/reset-password", status_code=204)
    def reset_password(
        payload: PasswordResetConfirm,
        db: Session = Depends(get_db),
    ) -> None:
        reset = db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token == payload.token,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(timezone.utc),
            )
        )
        if reset is None:
            raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
        user = db.get(User, reset.user_id)
        if user is None:
            raise HTTPException(status_code=400, detail="User not found")
        user.password_hash = auth_service.hash_password(payload.new_password)
        reset.used_at = datetime.now(timezone.utc)
        db.commit()

Add rate limiting to both endpoints (use the existing slowapi limiter from app.core.rate_limit):
- POST /request-password-reset: @limiter.limit("3/minute")
- POST /reset-password: @limiter.limit("5/minute")

---

BACKEND — New model: backend/app/models/password_reset.py

    from datetime import datetime
    import uuid
    from sqlalchemy import Column, String, DateTime, ForeignKey
    from sqlalchemy.dialects.postgresql import UUID
    from app.db.base import Base

    class PasswordResetToken(Base):
        __tablename__ = "password_reset_tokens"
        id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
        user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        token = Column(String(64), nullable=False, unique=True, index=True)
        expires_at = Column(DateTime(timezone=True), nullable=False)
        used_at = Column(DateTime(timezone=True), nullable=True)
        created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(__import__('datetime').timezone.utc))

---

BACKEND — New Alembic migration

Create backend/alembic/versions/20260310_0033_password_reset_tokens.py

    def upgrade():
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_prt_token", "password_reset_tokens", ["token"], unique=True)
        op.create_index("ix_prt_user_id", "password_reset_tokens", ["user_id"])

    def downgrade():
        op.drop_table("password_reset_tokens")

Set down_revision to the current latest migration ID found in backend/alembic/versions/.

---

MOBILE — mobile/src/screens/ForgotPasswordScreen.tsx (new file)

Create a new screen with two states: REQUEST state (email input) and RESET state (new password input, shown when app opens via doordrill://reset-password?token=...).

REQUEST state UI:
- Email input field (same style as LoginScreen)
- "Send Reset Link" button
- On submit: POST /auth/request-password-reset → show success message "Check your email for a reset link"
- "Back to Sign In" link

RESET state UI (when token param is present in navigation):
- New password input (secureTextEntry)
- Confirm password input (secureTextEntry)
- "Set New Password" button
- Validates passwords match before submitting
- On submit: POST /auth/reset-password → navigate to LoginScreen with success message

Add the screen to the navigation stack in the root navigator. Add a "Forgot password?" link below the Sign In button in LoginScreen.tsx that navigates to ForgotPasswordScreen.

Handle the deep link doordrill://reset-password?token=... in App.tsx alongside the existing invite link handler:
    if (parsed.path === "reset-password" && parsed.queryParams?.token) {
        navigationRef.navigate("ForgotPassword", { token: parsed.queryParams.token as string });
    }

---

After implementing, verify:
1. POST /request-password-reset always returns 204 (no email enumeration)
2. POST /reset-password returns 400 for expired or used tokens
3. Token is single-use (used_at set on first use, second use rejected)
4. Rate limiting applied to both endpoints
5. ForgotPasswordScreen renders in both request and reset states
6. "Forgot password?" link visible on LoginScreen
7. Run alembic upgrade head against dev DB and confirm migration applies cleanly
```

---

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
| 5-A | `backend/Dockerfile`, `fly.toml` | 5-B, 5-C |
| 5-B | `main.py`, `config.py`, `.env.example` | 5-A, 5-C — but 1-A must finish first |
| 5-C | `api/auth.py`, new model, new migration, `ForgotPasswordScreen.tsx`, `LoginScreen.tsx`, `App.tsx` | 5-A, 5-B |

## Codex Validation Checklist

Before marking any Batch 5 prompt complete, Codex must verify the following against `backend/docs/ops/staging-prod-env-matrix.md`:

**5-A (Dockerfile / fly.toml)**
- [ ] `docker build -t doordrill-backend backend/` completes without error
- [ ] `docker run --env-file backend/.env doordrill-backend` starts and `/health` returns 200
- [ ] `fly.toml` has `[http_service]` pointing at port 8000 with `force_https = true`
- [ ] Image runs as non-root user (`USER appuser` or equivalent)

**5-B (Sentry)**
- [ ] `SENTRY_DSN` present in `.env.example` (value redacted) and loaded in `config.py`
- [ ] Sentry initialised before first request in `main.py` with `traces_sample_rate`, `environment`, and `_scrub_sentry_event` `before_send` hook
- [ ] SQLAlchemy integration enabled (`SqlalchemyIntegration()`)
- [ ] Passwords, tokens, and API keys do NOT appear in Sentry breadcrumbs (verified by `_scrub_sentry_event` unit test)

**5-C (Password Reset)**
- [ ] `password_reset_tokens` table migration applies cleanly: `alembic upgrade head`
- [ ] `POST /auth/request-password-reset` always returns 204 regardless of whether email exists (no enumeration)
- [ ] `POST /auth/reset-password` marks token used after one successful reset; second attempt returns 400
- [ ] Token expires after 2 hours; expired token returns 400
- [ ] `ForgotPasswordScreen.tsx` reachable from `LoginScreen.tsx` via "Forgot password?" link
- [ ] Deep link `doordrill://reset-password?token=...` opens `ResetPasswordScreen` in Expo

## Remaining items that are NOT Codex prompts

See `backend/docs/ops/staging-prod-env-matrix.md` for the full **Release Readiness Gate** (9 items) and **Observability Minimum** checklist. Key manual steps:

- Rotate `JWT_SECRET` → edit `.env` directly (never commit)
- Set `AUTH_REQUIRED=true`, `ENVIRONMENT=production` → edit `.env`
- Populate all required env vars listed in the ops matrix (DATABASE_URL pooler, REDIS_URL, DEEPGRAM_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, SENTRY_DSN)
- Run `alembic upgrade head` against production database
- Set Redis password in connection string (`redis://:password@host:6379/0`)
- Configure S3 bucket CORS policy via AWS console
- Set up Deepgram and ElevenLabs usage alerts in each provider's dashboard
- **Fly.io deploy**: `fly auth login` → `fly launch` (or `fly deploy` if app already exists) from repo root
- Verify Fly health check passes: `fly status` shows `running`, `GET /health` returns `{"status":"ok"}`
- Run stress tests: `python stress_test.py --turns 4` and `--concurrent 3`
- Run `backend/scripts/e2e_smoke_test.py` against staging URL before every production deploy
