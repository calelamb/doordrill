# DoorDrill Manager Dashboard

The dashboard is a Vite + React application for manager workflows across assignments, replay, analytics, and coaching actions.

## Requirements

- Node.js 20+
- npm 10+

## Local Setup

```bash
cd dashboard
npm install
cp .env.example .env
npm run dev
```

The development server runs on port `5174`.

## Runtime Configuration

The dashboard reads the following optional environment variables:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_WS_BASE_URL=ws://127.0.0.1:8000
```

During local development, the Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

## Validation

```bash
cd dashboard
npm run build
```

## Current Surface Area

- manager feed
- session replay and transcript review
- score override
- follow-up assignment creation
- manager analytics
- rep progress snapshots
- manager action timeline
- rep-mode drill console backed by `WS /ws/sessions/{id}`

## Local Auth Notes

- Local development supports the backend's header-based auth scaffold.
- Enter a manager identifier in the UI to load manager-scoped data when running against the local backend.
