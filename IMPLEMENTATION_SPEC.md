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

Supporting tables:
- `organizations`
- `teams`
- `users`
- `scenarios`

## API Contracts Implemented

### REST endpoints

- `POST /manager/assignments`
- `GET /manager/feed?manager_id=...`
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
  - `backend/app/services/ledger_buffer.py`
  - `backend/app/services/ledger_service.py`
  - `backend/app/services/grading_service.py`
  - `backend/app/services/manager_feed_service.py`
  - `backend/app/services/storage_service.py`
- Tests:
  - `backend/tests/test_manager_rep_flow.py`

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
- tests pass (`4 passed`)

## What Is Stubbed vs Production-Ready

Production-ready structure:
- service boundaries
- WS/REST contracts
- relational schema
- manager workflows + replay plumbing
- ledger persistence flow

Stubbed integrations:
- Deepgram STT (currently simulated transcript handling)
- LLM conversation provider (currently deterministic orchestrator output)
- ElevenLabs TTS (currently placeholder audio payload in WS events)
- S3/R2 presigned URL generation (currently placeholder URL builder)

## Required Next Steps (Priority Order)

1. Provider integration
   - wire Deepgram streaming STT
   - wire LLM streaming responses
   - wire ElevenLabs streaming TTS
   - preserve existing event contract

2. Replay fidelity hardening
   - align artifact timestamps with turn boundaries
   - persist richer objection tags and stage transitions

3. Auth and authorization
   - add real auth (Firebase/Supabase/JWT)
   - enforce manager/rep/org access controls on every endpoint

4. Infra readiness
   - add Alembic migrations
   - add structured logging + tracing
   - configure Redis + Postgres + object storage in deployment

5. Performance and reliability
   - load test to 200 concurrent sessions
   - verify p50/p95 first-audio latency
   - test event loss guarantees and reconnect behavior

6. Frontend integration
   - manager UI: feed, replay, override
   - rep UI: assignments, live drill, scorecard view

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
