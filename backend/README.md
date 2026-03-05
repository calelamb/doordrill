# DoorDrill Backend (v1 Foundation)

FastAPI backend implementing the AI trainer core loop with an immutable interaction ledger.

## Implemented Services

- `api-gateway`: REST endpoints for manager + rep workflows.
- `realtime-voice`: WebSocket endpoint with streaming event protocol.
- `conversation-orchestrator`: stage-aware response generator (provider abstraction point).
- `session-ledger-service`: buffered event capture + batched persistence.
- `grading-service`: async scorecard generation with evidence turn linking.
- `manager-feed-service`: manager timeline with replay and review visibility.
- `postprocess-service`: transcript cleanup + grading + manager notifications (inline or Celery queued).

## Data Model

Core tables included:
- `assignments`
- `sessions`
- `session_events`
- `session_turns`
- `session_artifacts`
- `scorecards`
- `manager_reviews`
- `manager_action_logs`

Plus org/user/team/scenario tables.

## API Surface

REST:
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `GET /scenarios`
- `POST /scenarios`
- `GET /scenarios/{scenario_id}`
- `PUT /scenarios/{scenario_id}`
- `GET /manager/team?manager_id=...`
- `POST /manager/assignments`
- `GET /manager/assignments?manager_id=...`
- `POST /manager/scorecards/{scorecard_id}/followup-assignment`
- `GET /manager/feed?manager_id=...`
- `GET /manager/reps/{rep_id}/progress?manager_id=...`
- `GET /manager/analytics?manager_id=...`
- `GET /manager/actions?manager_id=...`
- `GET /manager/sessions?manager_id=...`
- `GET /manager/sessions/{session_id}`
- `GET /manager/sessions/{session_id}/audio`
- `GET /manager/sessions/{session_id}/replay`
- `PATCH /manager/scorecards/{scorecard_id}`
- `GET /rep/assignments?rep_id=...`
- `POST /rep/sessions`
- `GET /rep/sessions?rep_id=...`
- `GET /rep/sessions/{session_id}`
- `GET /rep/progress?rep_id=...`

WebSocket:
- `WS /ws/sessions/{session_id}`
- `WS /ws/session/{session_id}` (architecture alias)

Supported client events:
- `client.audio.chunk`
- `client.vad.state`
- `client.session.end`

Server events:
- `server.session.state`
- `server.stt.partial`
- `server.stt.final`
- `server.ai.text.delta`
- `server.ai.audio.chunk`
- `server.turn.committed`
- `server.error`

Replay additions:
- interruption timeline (`barge_in_detected` state events)
- transport metric: `barge_in_count`

## Auth / RBAC Scaffold

- Header-based actor identity is supported via:
  - `x-user-id`
  - `x-user-role` (`rep`, `manager`, `admin`)
- JWT mode is also supported:
  - `Authorization: Bearer <token>`
  - token claims: `sub`/`user_id`, `role`
- External IdP JWT validation is supported via `JWT_JWKS_URL` (JWKS key discovery).
- `AUTH_MODE=jwt` + `AUTH_REQUIRED=true` enforces bearer auth.
- `AUTH_REQUIRED=true` enforces header presence.
- Manager and rep endpoints enforce role- and org-aware access checks.
- Scorecards now include `weakness_tags`, and follow-up assignments can embed those tags into retry policy metadata.
- Manager mutation workflows write audit events to `manager_action_logs`.
- Local auth endpoints issue JWT access/refresh tokens; JWKS verification remains supported for external IdPs.

## Run

```bash
cd backend
python -m uvicorn app.main:app --reload
```

## Database Migrations

```bash
cd backend
alembic upgrade head
```

Initial migration is in `alembic/versions/20260305_0001_initial_schema.py`.

## Test

```bash
cd backend
pytest
```

## Load / SLO Harness

```bash
cd backend
python scripts/load_test_ws.py \
  --manager-id <manager_id> \
  --rep-id <rep_id> \
  --scenario-id <scenario_id> \
  --ramp 50,100,200 \
  --slo-p50-ms 900 \
  --slo-p95-ms 1400 \
  --min-success-rate 0.99 \
  --verify-replay \
  --report-json ./load-reports/ws-ramp.json
```

## Notes

- Redis buffering is enabled automatically if `REDIS_URL` is provided.
- Post-session workflow can run via Celery (`USE_CELERY=true`) with Redis broker/backend.
- Storage URLs now support S3/R2 presigning when object storage credentials are configured; otherwise fallback URLs are returned for local dev.
- Provider adapters for Deepgram/OpenAI/ElevenLabs are wired with real API paths plus mock fallback behavior to keep local development deterministic.
- Grading uses OpenAI judge mode when API credentials are present, with normalized JSON output and deterministic fallback scoring.
- Whisper transcript cleanup hook is implemented and runs when `WHISPER_CLEANUP_ENABLED=true`.
- Structured JSON logs now include request/session trace fields (`trace_id`, `request_id`) for HTTP and websocket flows.
