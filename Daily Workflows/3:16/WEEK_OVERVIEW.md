# Week of 3/16 — DoorDrill Launch Sprint

**Goal:** App submitted to both stores by Friday EOD.

---

## State of the Codebase

| Area | Status |
|------|--------|
| Backend core (auth, WebSocket drill, grading, RAG) | ✅ Done |
| Mobile (auth, push notifications, onboarding, deep links) | ✅ Done |
| Manager dashboard (web) | ✅ Done |
| Codex Batches 1–4 | ✅ Done |
| Codex Batch 5 (Dockerfile, Sentry, password reset) | ❌ Not started |
| Fly.io production deploy | ❌ Not started |
| Apple Developer account | ❌ Not started |
| Google Play account | ❌ Not started |
| EAS Build configured | ❌ Not started |
| Push notification credentials (APNs, FCM) | ❌ Not started |
| Privacy policy + ToS hosted | ❌ Not started |
| Store screenshots + listing copy | ❌ Not started |
| Physical device QA | ❌ Not started |

---

## The Week at a Glance

| Day | Engineering (Codex/Terminal) | You (Accounts/Assets) |
|-----|-----------------------------|-----------------------|
| **Mon 3/16** | Run Batch 5 Codex prompts (5-A, 5-B, 5-C) | Enroll Apple Developer, Google Play, sign up for Resend |
| **Tue 3/17** | Fly.io deploy, secrets, alembic, smoke test | Wire Resend API key, verify email delivery |
| **Wed 3/18** | app.json config, EAS Build, iOS Privacy Manifest | APNs key, Firebase/FCM setup, production URL in app |
| **Thu 3/19** | QA smoke test on device | Privacy policy + ToS, app icon, screenshots, listing copy |
| **Fri 3/20** | EAS production builds | Submit Android to Internal Testing, submit iOS to App Store |

---

## Daily Files

- [Monday 3/16](./MON_3_16.md)
- [Tuesday 3/17](./TUE_3_17.md)
- [Wednesday 3/18](./WED_3_18.md)
- [Thursday 3/19](./THU_3_19.md)
- [Friday 3/20](./FRI_3_20.md)

---

## Key Reference Docs

- Production Codex Prompts: `docs/ops/PRODUCTION_CODEX_PROMPTS.md`
- Production Checklist: `docs/ops/PRODUCTION_CHECKLIST.md`
- App Store Launch Checklist: `Daily Workflows/launch/app-store-launch-checklist.md`
- Ops Matrix (env vars, readiness gate): `backend/docs/ops/staging-prod-env-matrix.md`
