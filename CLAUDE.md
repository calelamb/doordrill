# DoorDrill

AI-powered sales training platform: reps practice door-to-door pitches against an AI homeowner via voice, managers review scorecards and coach their teams.

## Architecture

Monorepo with three packages:

```
backend/     → Python 3.11+ / FastAPI / SQLAlchemy / Alembic (REST + WebSocket)
dashboard/   → React 18 / Vite / TypeScript / Tailwind CSS (manager web UI)
mobile/      → Expo 54 / React Native / TypeScript (rep mobile app, iOS + Android)
```

**Database:** SQLite for local dev, PostgreSQL + pgvector for production.
**AI providers:** STT (Deepgram), LLM (OpenAI/Anthropic), TTS (ElevenLabs) — all have mock fallbacks.
**State management:** Zustand (mobile), React context (dashboard).

## Commands

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"         # install deps (includes pytest)
cp .env.example .env          # first time only
python3 -m uvicorn app.main:app --reload --port 8000
pytest                         # run tests (SQLite in-memory, mock providers)
pytest tests/test_auth_login.py           # single test file
pytest tests/test_auth_login.py -k "test_name"  # single test
alembic upgrade head           # run migrations
alembic revision --autogenerate -m "description"  # create migration

# Dashboard
cd dashboard
npm install
npm run dev                    # Vite dev server on :5174, proxies /api → :8000
npm run build                  # tsc -b && vite build

# Mobile
cd mobile
npm install
npx expo start                 # Expo dev server
npx expo run:ios               # native iOS build
npm run typecheck              # tsc --noEmit
```

## Key Files

| Purpose | Path |
|---------|------|
| Backend entry point | `backend/app/main.py` |
| Settings / env vars | `backend/app/core/config.py` |
| Auth (JWT, Actor, dependencies) | `backend/app/core/auth.py` |
| API routes | `backend/app/api/{auth,rep,manager,admin,scenarios}.py` |
| WebSocket voice pipeline | `backend/app/voice/ws.py` |
| SQLAlchemy models | `backend/app/models/` |
| Pydantic schemas | `backend/app/schemas/` |
| Business logic services | `backend/app/services/` (30 files) |
| Alembic migrations | `backend/alembic/versions/` |
| Dashboard API client | `dashboard/src/lib/api.ts` |
| Mobile navigation | `mobile/src/navigation/` |
| Mobile Zustand stores | `mobile/src/store/` |
| CI/CD | `.github/workflows/backend-slo-gate.yml` |
| Scripts (smoke/load tests, seeding) | `scripts/` |

## Code Style & Conventions

- **Backend:** Pydantic v2 models for all request/response schemas. SQLAlchemy 2.0 style (select/scalar). Services are plain classes instantiated at module level in route files.
- **Auth:** `Actor` dataclass resolved via `get_actor` dependency. Use `require_manager`, `require_admin`, or `require_rep_or_manager` as FastAPI dependencies.
- **Multi-tenancy:** All org-scoped queries must call `_ensure_same_org(actor, resource.org_id)`. This helper rejects when `actor.org_id` is None.
- **Dashboard:** Tailwind CSS v4 via `@tailwindcss/vite` plugin. Pages in `src/pages/`, shared components in `src/components/`.
- **Mobile:** Screen components in `src/screens/`, services call REST API via `src/services/api.ts`. Deep link scheme: `doordrill://`.
- **No linter/formatter configured** — no ESLint, Prettier, ruff, or black.

## Testing

- Backend only: `cd backend && pytest` (73 test files in `tests/`)
- Test DB: SQLite in-memory, auto-created via `conftest.py`
- Fixtures auto-set all providers to mock mode
- CI runs pytest + auth mode tests + Alembic migration smoke + WebSocket load tests
- Dashboard/mobile: type-check only (`tsc`), no test runner

## Environment

All providers default to `mock` for local dev — no API keys needed to run.
Set `AUTH_REQUIRED=False` (default) to skip JWT in dev.
Dashboard Vite proxy rewrites `/api/*` → backend on `:8000`.
Mobile reads API URL from `app.json` extra config.

## Gotchas

- Use `python3` not `python` — macOS may not have `python` on PATH.
- No virtualenv is pre-configured; create one manually (`python3 -m venv .venv`).
- `_ensure_same_org` is duplicated in `rep.py`, `manager.py`, and `scenarios.py` — changes must be applied to all three.
- Admin endpoints (`/admin/*`) require `require_admin` dependency, not `require_manager`.
- `POST /auth/register` does NOT allow `role: "admin"` — admin accounts must be created through other means.
- The mobile app uses Hermes JS engine (configured in `ios/Podfile.properties.json`).
- Alembic migrations target SQLite by default; PostgreSQL may need dialect-specific adjustments.
