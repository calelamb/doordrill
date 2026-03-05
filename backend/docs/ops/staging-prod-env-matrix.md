# DoorDrill Backend Staging/Prod Environment Matrix

This matrix defines the minimum infrastructure and environment configuration required to run v1 reliably.

## Service Topology

| Component | Staging | Production | Notes |
| --- | --- | --- | --- |
| FastAPI API/WebSocket | 1-2 replicas | 3+ replicas | Single region US for v1 |
| Postgres | Managed, HA disabled acceptable | Managed HA required | Source of truth for ledger/replay |
| Redis | Shared cache/queue | Dedicated queue + cache | Used for WS buffer and Celery |
| Celery Worker | 1 worker process minimum | Autoscaled pool | Executes cleanup/grade/notify tasks |
| Celery Beat | 1 scheduler process | HA scheduler or managed equivalent | Required for retry sweepers |
| Object Storage | S3/R2 bucket | S3/R2 bucket | Audio/transcript artifacts only as keys in DB |
| Notification Providers | Sandbox/test keys | Live keys | SendGrid + Expo push |

## Required Environment Variables

### Core Runtime

| Variable | Staging | Production |
| --- | --- | --- |
| `ENVIRONMENT` | `staging` | `prod` |
| `DATABASE_URL` | required | required |
| `REDIS_URL` | required | required |
| `AUTH_REQUIRED` | `true` outside local sandboxes | `true` | Required for JWT-backed mobile/web clients |
| `AUTH_MODE` | `jwt` | `jwt` | WebSocket auth uses the same JWT access token |
| `JWT_SECRET` or `JWT_JWKS_URL` | required | required | Must match REST and WS auth verification |
| `USE_CELERY` | `true` | `true` |
| `CELERY_BROKER_URL` | required | required |
| `CELERY_RESULT_BACKEND` | required | required |

### Voice/Model Providers

| Variable | Staging | Production |
| --- | --- | --- |
| `STT_PROVIDER` | `deepgram` | `deepgram` |
| `LLM_PROVIDER` | `openai` | `openai` |
| `TTS_PROVIDER` | `elevenlabs` | `elevenlabs` |
| `DEEPGRAM_API_KEY` | required | required |
| `OPENAI_API_KEY` | required | required |
| `ELEVENLABS_API_KEY` | required | required |
| `ELEVENLABS_VOICE_ID` | required | required |
| `PROVIDER_TIMEOUT_SECONDS` | `<=10` | `<=10` |

### Artifact Storage

| Variable | Staging | Production |
| --- | --- | --- |
| `STORAGE_BUCKET` | required | required |
| `OBJECT_STORAGE_ENDPOINT` | required (if non-AWS) | required (if non-AWS) |
| `OBJECT_STORAGE_REGION` | required | required |
| `OBJECT_STORAGE_ACCESS_KEY` | required | required |
| `OBJECT_STORAGE_SECRET_KEY` | required | required |
| `OBJECT_STORAGE_PUBLIC_BASE_URL` | optional | recommended |

### Notifications + Postprocess

| Variable | Staging | Production |
| --- | --- | --- |
| `WHISPER_CLEANUP_ENABLED` | `true` | `true` |
| `MANAGER_NOTIFICATION_EMAIL_ENABLED` | `true` | `true` |
| `MANAGER_NOTIFICATION_PUSH_ENABLED` | `true` | `true` |
| `NOTIFICATION_PUSH_PROVIDER` | `expo` or `fcm` | `expo` or `fcm` | Device token provider is inferred if the client omits it |
| `SENDGRID_API_KEY` | required | required |
| `SENDGRID_FROM_EMAIL` | required | required |
| `EXPO_PUSH_ACCESS_TOKEN` | optional | recommended |
| `FCM_SERVER_KEY` | optional | required if `NOTIFICATION_PUSH_PROVIDER=fcm` |
| `NOTIFICATION_MAX_RETRIES` | `5` | `5` |
| `NOTIFICATION_RETRY_BASE_SECONDS` | `30` | `30` |

## Release Readiness Gate

1. `alembic upgrade head` succeeds in target env.
2. Celery worker consumes:
   - `post_session.cleanup`
   - `post_session.grade`
   - `post_session.notify`
   - `post_session.retry_due`
   - `notifications.retry_due`
3. Celery beat is running and retry sweeps execute once per minute.
4. Auth-mode smoke passes for:
   - `/auth/register`
   - JWT-backed `/ws/sessions/{id}?access_token=...`
5. SLO harness passes `50/100/200` ramp with JSON report retained.
6. Replay spot check passes for at least 20 sessions:
   - transcript turn count > 0
   - turn linkage present in `server.turn.committed`
   - audio artifact key resolves to signed URL
7. Notification delivery table shows successful sends with retries < threshold and no `retry_scheduled` buildup.

## Observability Minimum

- Metrics dashboard:
  - first AI audio latency p50/p95
  - barge-in latency p95
  - queue depth by postprocess task
  - notification delivery success/failure/retry counts
  - retry sweeper processed count per minute
- Logs include:
  - `trace_id`
  - `session_id`
  - task id/status transitions (`postprocess_runs`)
  - websocket auth failures without logging raw `access_token` query values
