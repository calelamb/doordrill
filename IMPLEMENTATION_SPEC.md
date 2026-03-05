# DoorDrill v1 Implementation Spec (Agent Handoff)

## Purpose

This document is the starting point for future Codex agents. It captures what has already been implemented, the required architecture, the active contracts, and what should be built next.

## Product Goal

DoorDrill must become the leading AI training system for D2D sales teams.

Core moat:
- Real-time, realistic AI homeowner voice roleplay
- Complete storage of all rep-model interactions in our DB
- Manager workflows built on top of that interaction ledger:
  - assign roleplays
  - review full replay
  - see AI grades + evidence
  - override grades and coach

## Current Repo State

The backend foundation is implemented under:
- `backend/`
The manager dashboard scaffold is implemented under:
- `dashboard/`

Top-level docs:
- `README.md`
- `architecture.md`
- `IMPLEMENTATION_SPEC.md` (this file)

## Implemented Architecture

### Services implemented

1. API gateway (FastAPI REST)
2. Realtime voice gateway (FastAPI WebSocket)
3. Conversation orchestrator (stage-aware response engine; provider integration point)
4. Session ledger service (buffer + batched event persistence)
5. Grading service (async scorecard generation + evidence turn IDs)
6. Manager feed service (timeline for review workflows)

### Data model implemented

Must-have tables are present:
- `assignments`
- `sessions`
- `session_events` (immutable event rows with idempotency via unique `event_id`)
- `session_turns` (normalized transcript turns)
- `session_artifacts` (audio/transcript artifact index)
- `scorecards`
- `manager_reviews`
- `manager_action_logs`

Supporting tables:
- `organizations`
- `teams`
- `users`
- `scenarios`

## API Contracts Implemented

### REST endpoints

- `POST /manager/assignments`
- `POST /manager/scorecards/{scorecard_id}/followup-assignment`
- `GET /manager/feed?manager_id=...`
- `GET /manager/reps/{rep_id}/progress?manager_id=...`
- `GET /manager/analytics?manager_id=...`
- `GET /manager/actions?manager_id=...`
- `GET /manager/sessions/{session_id}/replay`
- `PATCH /manager/scorecards/{scorecard_id}`
- `GET /rep/assignments?rep_id=...`
- `POST /rep/sessions`
- `GET /rep/sessions/{session_id}`
- `GET /health`

### WebSocket endpoint

- `WS /ws/sessions/{session_id}`

#### Supported client events
- `client.audio.chunk`
- `client.vad.state`
- `client.session.end`

#### Server events emitted
- `server.session.state`
- `server.stt.partial`
- `server.stt.final`
- `server.ai.text.delta`
- `server.ai.audio.chunk`
- `server.turn.committed`
- `server.error`

## Ledger and Persistence Behavior

1. Incoming/outgoing WS events are buffered first (Redis if configured, otherwise in-memory).
2. Events are flushed to `session_events` in batches on a timed interval.
3. Idempotency is enforced by unique `event_id` in `session_events`.
4. Rep/AI turns are committed to `session_turns`.
5. On session end:
   - remaining buffered events are flushed
   - canonical transcript artifact is compacted into `session_artifacts`
   - audio artifact record is written to `session_artifacts`
   - session transitions to `processing`, then graded
   - assignment transitions to `completed`

## Manager Experience Implemented

`GET /manager/feed` currently returns:
- session id
- rep id
- assignment id
- overall score (if graded)
- category scores
- highlights
- manager_reviewed flag
- assignment status
- session status

`GET /manager/sessions/{id}/replay` currently returns:
- full transcript turns
- objection timeline
- audio artifact metadata + signed URL placeholder
- scorecard details + evidence turn references

`PATCH /manager/scorecards/{id}` supports:
- reason-coded manager override
- optional override score
- notes
- audit row creation in `manager_reviews`

`POST /manager/scorecards/{id}/followup-assignment` supports:
- creating next-assignment directly from scorecard context
- embedding `weakness_tags` in retry metadata for adaptive drill routing

`GET /manager/reps/{rep_id}/progress` supports:
- rep-level trend and recent session performance retrieval

`GET /manager/analytics` supports:
- manager/team-level assignment, completion, and score aggregates

`GET /manager/actions` supports:
- manager workflow audit trail retrieval from `manager_action_logs`

## File Map (Start Here)

- App boot:
  - `backend/app/main.py`
- DB/session bootstrap:
  - `backend/app/db/session.py`
  - `backend/app/db/init_db.py`
- Models:
  - `backend/app/models/`
- Schemas/contracts:
  - `backend/app/schemas/`
- REST APIs:
  - `backend/app/api/manager.py`
  - `backend/app/api/rep.py`
- Realtime WS flow:
  - `backend/app/voice/ws.py`
- Core services:
  - `backend/app/services/conversation_orchestrator.py`
  - `backend/app/services/provider_clients.py`
  - `backend/app/services/ledger_buffer.py`
  - `backend/app/services/ledger_service.py`
  - `backend/app/services/grading_service.py`
  - `backend/app/services/manager_feed_service.py`
  - `backend/app/services/manager_action_service.py`
  - `backend/app/services/storage_service.py`
- Migrations:
  - `backend/alembic/`
  - `backend/alembic/versions/20260305_0001_initial_schema.py`
  - `backend/alembic/versions/20260305_0002_scorecard_weakness_tags.py`
  - `backend/alembic/versions/20260305_0003_org_audit_and_indexes.py`
- Tests:
  - `backend/tests/test_manager_rep_flow.py`
  - `backend/tests/test_auth_rbac.py`
  - `backend/tests/test_org_data_guardrails.py`
  - `backend/tests/test_provider_clients.py`
- Dashboard:
  - `dashboard/src/App.tsx`
  - `dashboard/src/components/FeedList.tsx`
  - `dashboard/src/components/PerformancePanel.tsx`
  - `dashboard/src/components/RepPanel.tsx`
  - `dashboard/src/components/ReplayPanel.tsx`
  - `dashboard/src/lib/api.ts`

## How to Run

```bash
cd backend
python -m uvicorn app.main:app --reload
```

## How to Test

```bash
cd backend
pytest
```

Current status:
- tests pass (`17 passed`)

## What Is Stubbed vs Production-Ready

Production-ready structure:
- service boundaries
- WS/REST contracts
- relational schema
- manager workflows + replay plumbing
- ledger persistence flow
- grading pipeline with LLM-judge path + deterministic fallback

Stubbed integrations:
- Deepgram STT (real API path implemented with mock fallback)
- LLM conversation provider (OpenAI streaming path implemented with mock fallback)
- ElevenLabs TTS (streaming path implemented with mock fallback)

## Required Next Steps (Priority Order)

1. Provider integration
   - implemented provider adapters and fallback behavior
   - next: validate with real keys in staging and tune latency budgets

2. Replay fidelity hardening
   - turn timing alignment implemented in WS turn commit windows
   - interruption-aware traces implemented (`barge_in_detected` + replay interruption timeline)
   - next: benchmark barge-in cancel latency against <=150ms target with provider-backed runs

3. Auth and authorization
   - header + JWT actor resolution implemented
   - org-level endpoint guards implemented
   - next: wire external identity provider token lifecycle

4. Infra readiness
   - add Alembic migrations (implemented through rev `20260305_0003`)
   - structured logging + tracing implemented (JSON logs, request/session trace IDs)
   - configure Redis + Postgres + object storage in deployment

5. Performance and reliability
   - load test ramp harness implemented (`50,100,200` stages, SLO gates, JSON reports)
   - next: run staged benchmarks in deployed env and enforce CI gating on SLO failures
   - next: test event loss guarantees and reconnect behavior under network churn

6. Frontend integration
   - manager UI: feed, replay, override, analytics, action timeline implemented in scaffold
   - rep UI: assignments + session start + score fetch + live WS drill console implemented
   - next: microphone capture/streaming UX + auth/session hardening

## Non-Negotiable Product Requirements

Future implementations must preserve:
- full interaction capture in DB
- manager full replay visibility by default
- traceable AI grading evidence linked to transcript turns
- manager override auditability

## Notes for Future Agents

- Do not break the current WS event names unless you version the contract.
- Maintain at-least-once event persistence semantics with idempotency keys.
- Keep FastAPI as orchestration/control plane; do not move heavy ML inference into the API process.
- If replacing stubs, keep interfaces stable so tests and UI clients remain compatible.
