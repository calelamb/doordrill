# CLAUDE TODO

## Exactly What Was Just Finished

### Mobile (Track B) delivered
1. Replaced typed-turn live drill with real hold-to-talk microphone flow.
2. Added VAD signaling over websocket (`client.vad.state`) and real audio payload upload (`client.audio.chunk` with base64 audio).
3. Added reconnect handling and explicit interruption cueing in-session.
4. Added best-effort AI audio chunk playback queue on device.
5. Redesigned assignment list flow with filters and rep-facing status/target visibility.
6. Redesigned scorecard flow with category progress bars, highlights, weakness tags, and evidence count.

### Backend + Ops (Track A reliability) delivered
1. Upgraded WS load harness to gate on first-audio SLOs, barge-in latency SLO, and replay turn-link integrity.
2. Added deterministic seed utility for load/CI manager/rep/scenario IDs.
3. Added GitHub Actions workflow for staged `50/100/200` SLO gate with JSON artifact upload.
4. Added websocket network-churn integrity regression test (disconnect/reconnect path).
5. Added staging/prod environment matrix and incident runbook docs.

### Validation completed
1. Backend tests: `23 passed`.
2. Mobile typecheck: passes.

---

## Files Considered 100% Functional (Based On Current Validation)

Note: “100% functional” here means implemented and validated against current automated checks in this repo (not full real-device/production soak).

### Mobile voice/session loop
- `/Users/calelamb/Desktop/personal projects/doordrill/mobile/src/services/audio.ts`
- `/Users/calelamb/Desktop/personal projects/doordrill/mobile/src/services/websocket.ts`
- `/Users/calelamb/Desktop/personal projects/doordrill/mobile/src/screens/SessionScreen.tsx`

### Mobile assignment + score UX
- `/Users/calelamb/Desktop/personal projects/doordrill/mobile/src/components/AssignmentCard.tsx`
- `/Users/calelamb/Desktop/personal projects/doordrill/mobile/src/screens/AssignmentsScreen.tsx`
- `/Users/calelamb/Desktop/personal projects/doordrill/mobile/src/screens/ScoreScreen.tsx`

### Backend SLO/reliability tooling
- `/Users/calelamb/Desktop/personal projects/doordrill/backend/scripts/load_test_ws.py`
- `/Users/calelamb/Desktop/personal projects/doordrill/backend/scripts/seed_load_data.py`
- `/Users/calelamb/Desktop/personal projects/doordrill/backend/tests/test_ws_network_churn.py`
- `/Users/calelamb/Desktop/personal projects/doordrill/.github/workflows/backend-slo-gate.yml`
- `/Users/calelamb/Desktop/personal projects/doordrill/backend/docs/ops/staging-prod-env-matrix.md`
- `/Users/calelamb/Desktop/personal projects/doordrill/backend/docs/ops/incident-runbook.md`

---

## Where The UI Is Still Boring

### Mobile app
1. Visual system is still conservative: one-tone palette and standard card/chip patterns; not yet an industry-leading brand aesthetic.
2. Session screen is function-first and dense; event stream looks like debug tooling instead of premium coaching UX.
3. No meaningful motion language yet (no staggered transitions, state animations, or delight moments).
4. Scorecard lacks richer data viz (no radar chart, no turn-linked timeline scrubber).
5. Assignment cards are clearer than before but still generic; limited differentiation between critical vs routine drills.

### Dashboard/web surface
1. Manager replay UI polish from the plan is still incomplete in this phase.
2. Notification center UX parity is not yet deeply designed; current backend support exists, UI refinement still needed.

---

## Immediate Next UX Priorities

1. Upgrade session screen from “debug stream” to “coaching theater” (clean transcript/audio timeline + interruption badges + critical moments rail).
2. Add scorecard visualization upgrade (radar + evidence-linked turn jump controls).
3. Complete manager replay/notification surface polish to match backend capability.
