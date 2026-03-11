# DoorDrill

DoorDrill is a multi-surface AI training platform for door-to-door sales teams. Reps practice live objection handling against AI homeowners, sessions are graded automatically, and managers review performance through workflow and analytics tools.

## Repository Status

DoorDrill is in active pre-production development. Core backend contracts, the manager dashboard, and the mobile drill experience are implemented and under active iteration. Production hardening, deployment readiness, and operational maturity are being developed in parallel.

## Repository Layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI service, realtime voice gateway, grading pipeline, auth, and manager/rep APIs |
| `dashboard/` | React manager console for assignment, replay, analytics, and coaching workflows |
| `mobile/` | Expo React Native client for the rep training experience |
| `docs/` | Conformance notes, gap analyses, and operational documentation |
| `scenarios/` | Seed scenario and rubric definitions |
| `.github/` | CI workflow and GitHub collaboration metadata |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+

### Backend

```bash
cd backend
python -m pip install -e .[dev]
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The default local configuration uses SQLite and mock STT/LLM/TTS providers, so the service can run without external API credentials.

Run backend tests:

```bash
cd backend
pytest
```

### Dashboard

```bash
cd dashboard
npm install
cp .env.example .env
npm run dev
```

The dashboard runs on port `5174` and proxies `/api` traffic to `http://127.0.0.1:8000` during local development.

### Mobile

```bash
cd mobile
npm install
cp .env.example .env
npm run start
```

Use `npm run ios` or `npm run android` for native runs after the local Expo environment is configured.

## System Summary

DoorDrill currently consists of three user-facing surfaces backed by a shared service layer:

- `backend/`: FastAPI REST and WebSocket APIs, provider abstractions, session persistence, grading, analytics, and operational harnesses
- `dashboard/`: manager workflows for assignment, replay, action history, and progress tracking
- `mobile/`: rep login, assignment intake, live drill execution, and post-session scorecards

The deeper architecture, contract, and rollout details are documented separately to keep the root README focused on repository usage.

## Quality and Operations

- Backend CI is defined in [`.github/workflows/backend-slo-gate.yml`](./.github/workflows/backend-slo-gate.yml) and covers tests, auth smoke, migration smoke, realtime websocket load gates, and management analytics load gates.
- Backend operational references live under [`backend/docs/ops/`](./backend/docs/ops).
- Load and SLO tooling is documented in [`backend/scripts/README.md`](./backend/scripts/README.md).

## Documentation Index

- [`architecture.md`](./architecture.md): system architecture, data model, and implementation roadmap
- [`docs/ARCHITECTURE_CONFORMANCE.md`](./docs/ARCHITECTURE_CONFORMANCE.md): current endpoint and service parity tracking
- [`docs/README.md`](./docs/README.md): documentation map and source-of-truth guidance
- [`SECURITY.md`](./SECURITY.md): security reporting expectations
- [`backend/README.md`](./backend/README.md): backend setup, test, and operational entry points
- [`dashboard/README.md`](./dashboard/README.md): manager console setup and local development workflow
- [`mobile/README.md`](./mobile/README.md): mobile app setup and runtime configuration

## Contributing

This repository expects small, reviewable branches, accurate docs, and validation tied to the surface area being changed. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for branch, testing, and pull request expectations.
