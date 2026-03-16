# DoorDrill — Build Status

Last updated: 2026-03-11

---

## ✅ Done

### Core Backend
- FastAPI app with Supabase/PostgreSQL (pooler URL, IPv4 compatible)
- JWT auth — login, register, refresh, token validation
- WebSocket drill pipeline — Deepgram STT, GPT-4o, ElevenLabs TTS
- Session grading — `GradingService` with RAG via `DocumentRetrievalService`
- `SessionPostprocessService` — grading → manager notifications
- Manager assignment flow — `POST /manager/assignments`, sessions filtered by `assigned_by`
- Scenario CRUD — `POST /scenarios` with `created_by_id`
- Rate limiting on auth endpoints (`slowapi`, Batch 2-B)
- Ledger service — token/usage tracking
- S3 upload endpoints (Batch 4-A)
- `.gitignore` / secrets hygiene (Batch 4-B)
- Alembic migrations — 0032 applied to production Supabase DB

### Mobile (Expo)
- Real JWT auth replacing mock — `loginWithCredentials()`, `SecureStore` tokens, silent refresh
- Push notification infrastructure — `expo-notifications`, device token registration, 5 notification types
- Onboarding screens — 3-slide pager, first-drill guidance, manager checklist wizard
- `ForgotPasswordScreen.tsx` scaffold (wired to Batch 5-C backend)
- Deep link scheme `doordrill://`
- LAN IP auto-detection for dev (`Constants.expoConfig.hostUri`)

### Manager Dashboard (Web)
- Phase M1–M5 features built (3:6 session)
- Rep risk intelligence, AI coaching layer, real-time session monitor

### Testing
- `backend/scripts/e2e_smoke_test.py` — 22/24 passing
  - Full pipeline: auth → session → WebSocket drill (real GPT-4o/ElevenLabs) → grading → scorecard → manager view
  - 2 remaining failures are timing-related, not app bugs

### Docs & Planning
- `backend/docs/ops/staging-prod-env-matrix.md` — service topology, env vars, Release Readiness Gate
- `backend/docs/ops/incident-runbook.md`
- `docs/ops/PRODUCTION_CODEX_PROMPTS.md` — Batches 1–5 with validation checklists

---

## 🔄 In Progress (Codex Batch 5)

| Prompt | What | Status |
|--------|------|--------|
| 5-A | `backend/Dockerfile` + `fly.toml` | Not started |
| 5-B | Sentry integration | Not started |
| 5-C | Password reset (token model, API, mobile screens) | Not started |

---

## 📋 Not Started — Pre-Launch (Manual / Ops)

- [ ] Rotate `JWT_SECRET`, set `AUTH_REQUIRED=true`, `ENVIRONMENT=production` in Fly secrets
- [ ] Set all production env vars on Fly.io (`fly secrets set ...`)
- [ ] Run `alembic upgrade head` against production DB after Batch 5-C migration
- [ ] `fly deploy` and verify `/health` returns 200
- [ ] Run `e2e_smoke_test.py` against production URL

---

## 🚀 Not Started — App Store Launch

See `Daily Workflows/launch/app-store-launch-checklist.md` for the full checklist.

Key blockers before submission:
- [ ] Apple Developer Program enrollment ($99)
- [ ] EAS Build configured + production `.ipa` / `.aab` built
- [ ] APNs key + FCM credentials for push
- [ ] Privacy policy hosted at a public URL
- [ ] iOS Privacy Manifest (`PrivacyInfo.xcprivacy`)
- [ ] Screenshots + store listing copy
- [ ] Physical device QA (audio, push, WebSocket)
- [ ] Transactional email provider wired for password reset + manager invites (Resend / Postmark)

**Estimated timeline to App Store submission: 3–4 weeks**

---

## 🗃️ Deferred / Future

- Data warehouse layer (PRD: `Daily Workflows/3:7/PRD_DATA_WAREHOUSE_LAYER.md`)
- Predictive modeling / rep risk scoring (PRD: `Daily Workflows/3:7/PRD_PREDICTIVE_MODELING.md`)
- Manager AI chat (PRD: `Daily Workflows/3:7/PRD_MANAGER_AI_COACHING.md`)
- Conversational micro-behaviors engine (`docs/specs/CONVERSATIONAL_MICRO_BEHAVIORS_ENGINE.md`)
- Emotion simulation engine (`docs/specs/EMOTION_SIMULATION_ENGINE.md`)
- Adaptive training engine (`docs/specs/ADAPTIVE_TRAINING_ENGINE.md`)
- STT latency fix — target ≤500ms (currently 12–15s) (`Daily Workflows/CODEX_HANDOFF_STT_LATENCY.md`)
- Merge conversation orchestrator duplicate code (`Daily Workflows/MERGE_TODO.md`)
