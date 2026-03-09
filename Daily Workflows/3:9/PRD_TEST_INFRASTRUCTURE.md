# DoorDrill — Test Infrastructure Suite
## Phase Suite: TH1 → TH2 → TH3 → TH4

**Version:** 1.0
**Status:** Ready for Codex implementation
**Goal:** Test APIs, voice pipeline, and drill interactions without manual voice input.

---

## The Problem

Every time we change the voice pipeline (ws.py, conversation_orchestrator.py, provider_clients.py),
the only way to verify it works is to speak into the app manually, which takes 5–10 minutes and
catches maybe 20% of failure modes. We have:
- A broken test_ws_voice_pipeline.py (broke after sentence-parallel TTS rewrite)
- A stress_test.py that sends silent audio (real pipeline, no assertions on behavior)
- No API integration tests
- No scenario regression suite

This suite fixes all four gaps.

---

## Phase Catalog

| Phase | Focus | Speed | Requires Server? |
|-------|-------|-------|-----------------|
| TH1 | Fix + extend mock-based WS test | <5s | No |
| TH2 | Text-injection drill runner (scripted scenarios) | ~15s/drill | Yes |
| TH3 | Audio fixture generation + stress_test upgrade | ~3min/drill | Yes |
| TH4 | API integration test suite | <30s | No |

Run TH1 and TH4 on every PR. Run TH2 after any voice pipeline change. Run TH3 before deploys.

---

## Also Fix: Predictive Aggregate Staleness

Before the test phases, add this one-line fix to session_postprocess_service.run():

After `warehouse_etl_service.write_session(db, session_id)` succeeds, call:
  `warehouse_etl_service.refresh_predictive_aggregates(db, org_id=rep.org_id)`

This makes scenario outcome aggregates and cohort benchmarks refresh automatically after every
completed session instead of waiting for a manual refresh trigger. Wrap in try/except so a refresh
failure never blocks postprocess from completing.

---

## Codex Execution Guide

1. Paste `BOOTSTRAP_PROMPT.md` contents first in every Codex thread.
2. Paste the phase prompt below.
3. After each phase: `cd backend && python -m pytest tests/ -x -q`
4. Commit before moving to the next phase.

---

## Paste-Ready Phase Prompts

---

### PHASE TH0 — Fix predictive aggregate staleness (do this first, it's one method call)

```
Bootstrap is loaded. Fix a known gap in the session postprocess pipeline.

File to read first:
- backend/app/services/session_postprocess_service.py (full file)
- backend/app/services/warehouse_etl_service.py (specifically write_session and refresh_predictive_aggregates)

Goal:
In SessionPostprocessService.run_task_inline(), after the warehouse_etl_service.write_session()
call succeeds, add a call to warehouse_etl_service.refresh_predictive_aggregates(db, org_id=...).

To get org_id: look up the session's rep and read rep.org_id. If org_id cannot be resolved,
skip the refresh (log a warning, don't fail).

Wrap the refresh call in try/except Exception so a refresh failure never raises and never
blocks the postprocess run from completing. Log the result at DEBUG level.

Write test_predictive_aggregates_refresh_after_session.py:
- test_refresh_runs_after_write_session: monkeypatch refresh_predictive_aggregates, run
  run_task_inline(), assert it was called once with the correct org_id.
- test_refresh_failure_does_not_fail_postprocess: monkeypatch to raise, assert run_task_inline()
  still returns success.

Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE TH1 — Fix and extend mock-based WebSocket test

```
Bootstrap is loaded. Phase TH0 is complete.
Implement Phase TH1: fix the broken voice pipeline test and extend scenario coverage.

Files to read first:
- backend/tests/test_ws_voice_pipeline.py (full file — understand what's broken)
- backend/app/voice/ws.py (especially the sentence-parallel TTS pipeline, asyncio.gather,
  first_audio_started event, server.ai.text.done emission)
- backend/app/services/provider_clients.py (MockSttClient, MockLlmClient, MockTtsClient)

Context: test_ws_voice_pipeline.py broke after the sentence-parallel TTS rewrite. The mock
providers return events synchronously, but the new pipeline uses asyncio.Event
(first_audio_started) and asyncio.gather(*tts_tasks). The test likely hangs or fails on
server.ai.audio.chunk ordering assertions.

Goals:

1. FIX THE EXISTING TEST
   Diagnose exactly why test_ws_voice_pipeline_streams_events_in_order fails.
   - If MockTtsClient.stream_audio() is not async-compatible with the sentence-parallel loop,
     fix it so it yields at least one audio chunk and signals first_audio_started correctly.
   - If MockLlmClient yields tokens too fast for the drain loop, add a minimal asyncio.sleep(0)
     yield in the mock to let the event loop breathe.
   - Do not change the assertion logic — fix the mocks and the wiring, not the expectations.

2. ADD SCENARIO TESTS
   Add to test_ws_voice_pipeline.py (or a new file test_ws_drill_scenarios.py):

   test_edge_case_no_intro_triggers_on_first_turn:
   - Run a turn where the rep text contains no name or company ("Hi, is this a good time?").
   - Assert the server emits server.edge_case.triggered with tags containing "no_intro".

   test_premature_close_triggers_before_objection_stage:
   - Run turn 1 with a close attempt ("Can I get you scheduled today?").
   - Assert server.edge_case.triggered with "premature_close".

   test_tp3_objection_surfaces_in_considering_stage:
   - Initialize session with a scenario persona whose objection_queue contains "locked_in_contract".
   - Advance stage to "considering". Run a turn.
   - Assert that server.turn.committed payload includes "locked_in_contract" in active_objections
     or objection_tags.

   test_stage_aware_token_budget_used_at_correct_stage:
   - Mock the LLM client to capture the max_tokens argument it receives.
   - Run a turn at "door_knock" stage, assert max_tokens == 15.
   - Run a turn at "considering" stage, assert max_tokens == 45.

3. ADD POSTPROCESS CHAIN TEST
   test_session_end_triggers_postprocess_chain:
   - Complete a 2-turn session and send client.session.end.
   - Monkeypatch session_postprocess_service.enqueue_or_run to capture calls.
   - Assert it was called once with the correct session_id after session end.

4. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE TH2 — Text-injection drill runner

```
Bootstrap is loaded. Phase TH1 is complete.
Implement Phase TH2: a headless text-mode drill runner for scripted scenario testing.

This runner lets engineers test the full LLM→TTS pipeline with scripted rep dialogue
without speaking into a microphone. It runs against a live server.

Goals:

1. DEBUG TEXT-TURN ENDPOINT (ENV-GATED)
   Add POST /debug/sessions/{session_id}/text-turn to backend/app/api/debug.py (new file).
   Only register this router when settings.DEBUG_ENDPOINTS_ENABLED == True (default False).
   Request body: { "text": str, "sequence": int }
   Effect: identical to receiving a client.audio.chunk with transcript_hint=text.
   - Directly calls the session's STT finalize with the provided text (bypasses Deepgram).
   - Returns 200 with { "accepted": true }.
   Protect with the same auth as other session endpoints (Bearer token).

2. DRILL RUNNER SCRIPT
   Create backend/scripts/drill_runner.py.
   Usage:
     python scripts/drill_runner.py --scenario scenarios/standard_close.yaml
     python scripts/drill_runner.py --scenario scenarios/hostile_homeowner.yaml --verbose

   Each scenario YAML has:
     name: string
     turns:
       - rep: "Hi, I'm Alex with Acme Pest Control..."
         expect_events: ["server.stt.final", "server.ai.text.delta", "server.turn.committed"]
         expect_edge_cases: []           # optional: ["no_intro", "premature_close"]
         expect_emotion_not: ["hostile"] # optional: emotion that should NOT result
       - rep: "We protect against ants, spiders, and roaches..."
         expect_events: ["server.turn.committed"]

   Runner behavior:
   - Authenticates as a test rep (reads TEST_REP_EMAIL / TEST_REP_PASSWORD from .env).
   - Creates an assignment and session via REST API.
   - Connects via WebSocket.
   - For each turn: POSTs to /debug/sessions/{id}/text-turn, then drains WebSocket until
     server.turn.committed is received.
   - Asserts all expect_events appeared, no unexpected edge cases fired, no forbidden emotions.
   - Sends client.session.end when done.
   - Prints a summary table: turn | rep snippet | homeowner reply | events | assertions.
   - Exits 0 on pass, 1 on failure (suitable for CI).

3. SEED SCENARIO FILES
   Create backend/scripts/scenarios/ with three YAML files:
   - standard_close.yaml: 5-turn drill, rep introduces self, handles price objection, closes.
     No edge cases expected. Emotion should not reach "hostile".
   - no_intro_edge_case.yaml: Turn 1 has no name/company. Expects "no_intro" edge case.
   - premature_close.yaml: Turn 1 attempts a close. Expects "premature_close" edge case.

4. DOCUMENT USAGE
   Add a comment block at top of drill_runner.py explaining:
   - How to add scenarios
   - How to run against staging vs local
   - How to interpret the output table

5. No pytest tests required for this phase (the runner is itself the test harness).
   Verify manually that: python scripts/drill_runner.py --scenario scenarios/no_intro_edge_case.yaml
   passes with exit code 0 when server is running with DEBUG_ENDPOINTS_ENABLED=True.
```

---

### PHASE TH3 — Audio fixture generation + stress_test upgrade

```
Bootstrap is loaded. Phase TH2 is complete.
Implement Phase TH3: pre-recorded audio fixtures so stress_test.py can run real pipeline
regression without anyone speaking.

Goals:

1. FIXTURE GENERATION SCRIPT
   Create backend/scripts/generate_audio_fixtures.py.
   Usage: python scripts/generate_audio_fixtures.py
   - Reads ELEVENLABS_API_KEY from .env.
   - Synthesizes each phrase in FIXTURE_PHRASES (12 lines — see below) using ElevenLabs
     eleven_flash_v2_5 model, voice "Rachel" (voice_id: 21m00Tcm4TlvDq8ikWAM).
   - Saves each as backend/tests/fixtures/audio/turn_{n:02d}.wav (16kHz, mono, PCM WAV).
   - Skips files that already exist (idempotent).
   - Prints: "Generated N fixtures" when done.

   FIXTURE_PHRASES (D2D pest control scenario):
   01: "Hi there, hope I'm not catching you at a bad time. My name's Alex and I'm with Acme Pest Control. We're working in your neighborhood this week."
   02: "Totally understand. I'm not here to sell you anything today — just wanted to let you know we've helped a lot of families in this area get rid of ants, spiders, and roaches."
   03: "That makes sense. A lot of homeowners feel the same way until they realize how much easier it is than dealing with it yourself."
   04: "I completely hear you on the price. What we do is a monthly plan that works out to about the cost of a pizza. And we guarantee results or we come back for free."
   05: "I understand you'd want to talk to your spouse. What if I left you a one-pager you could both look over tonight? No pressure, no follow-up unless you reach out."
   06: "Fair enough. We actually just finished treating three houses on your block — your neighbors the Johnsons used us last month. We're licensed and insured, and our reviews are all public."
   07: "Not a problem at all. Is there a better time I could come back, or would you prefer I just leave you our info?"
   08: "I appreciate your honesty. Last thing I'll say — our initial inspection is completely free. You'd know exactly what you're dealing with before you commit to anything."
   09: "That's totally fair. A lot of people already have a provider and then they try us out when their contract ends. I can leave you a card in case that comes up."
   10: "I hear you, I do. We're not asking you to decide right now. If you ever notice anything — ants in the kitchen, spiders in the garage — give us a call and we'll come out same day."
   11: "Thank you so much for your time. I really appreciate it. Have a great rest of your day."
   12: "Of course, not a problem. You take care."

2. STRESS_TEST UPGRADE
   Add --fixture-audio flag to stress_test.py.
   When set, instead of generating silent WAV:
   - Load fixture WAV files from backend/tests/fixtures/audio/turn_{n:02d}.wav
     (cycle if turn count exceeds fixture count).
   - Send the actual PCM audio bytes as the audio chunk payload.
   - This causes Deepgram to produce a real transcript of the fixture speech.

   Add --baseline flag:
   - On first run with --baseline, save results to backend/tests/fixtures/latency_baseline.json.
   - On subsequent runs without --baseline, compare against baseline:
     If any metric exceeds baseline * 1.3 (30% regression), print a WARNING line for that metric.
   - Include: stt_ms, llm_first_token_ms, tts_first_chunk_ms, total_round_trip_ms per turn.

3. DOCUMENT IN EXISTING STRESS_TEST DOCSTRING
   Update the module docstring to include:
     python stress_test.py --fixture-audio           # use pre-recorded rep audio
     python stress_test.py --fixture-audio --baseline  # save latency baseline
     python stress_test.py --fixture-audio             # compare against baseline
   And: "Run generate_audio_fixtures.py once before using --fixture-audio."
```

---

### PHASE TH4 — API integration test suite

```
Bootstrap is loaded. Phase TH3 is complete.
Implement Phase TH4: comprehensive API integration tests for all manager and rep endpoints.

Files to read first:
- backend/app/api/manager.py (all endpoints)
- backend/app/api/rep.py (all endpoints)
- backend/tests/conftest.py (seed_org fixture — understand what data exists)

Goals:

1. MANAGER ENDPOINT TESTS
   Create backend/tests/test_api_manager_integration.py.
   Use the existing seed_org fixture and in-process TestClient. Test:

   Analytics endpoints:
   - test_command_center_returns_200_with_seed_data
   - test_team_analytics_returns_required_fields (score_trend, skill_heatmap, distribution)
   - test_rep_analytics_returns_required_fields (rep_id, score_history, category_breakdown)
   - test_scenario_intelligence_returns_required_fields
   - test_coaching_analytics_returns_required_fields
   - test_rep_forecast_returns_required_fields (rep_id, skill_forecasts, risk_score)
   - test_benchmarks_returns_required_fields

   Action endpoints:
   - test_override_scorecard_returns_200
   - test_override_scorecard_with_invalid_score_returns_422
   - test_create_coaching_note_returns_200
   - test_create_followup_assignment_returns_200

   Coaching AI endpoints:
   - test_rep_insight_endpoint_returns_200
   - test_one_on_one_prep_returns_required_fields
   - test_weekly_team_briefing_returns_required_fields

   Empty state tests:
   - test_rep_forecast_returns_empty_gracefully_with_no_sessions
   - test_benchmarks_returns_empty_gracefully_with_no_cohort_data

2. REP ENDPOINT TESTS
   Create backend/tests/test_api_rep_integration.py. Test:
   - test_create_session_returns_session_id
   - test_get_session_returns_correct_rep_id
   - test_list_assignments_returns_correct_rep
   - test_adaptive_plan_returns_required_fields

3. ADMIN ENDPOINT TESTS
   Create backend/tests/test_api_admin_integration.py. Test:
   - test_create_prompt_experiment_returns_201
   - test_list_prompt_experiments_returns_200
   - test_training_signal_export_returns_jsonl
   - test_training_signal_export_with_quality_filter

4. For each test: assert HTTP status code, assert top-level required fields exist in response,
   assert no 500 errors. Do NOT assert exact values — the seed data is synthetic and values
   will vary. Focus on shape and status.

5. Run pytest tests/ -x -q. All tests must pass.
```

---

## Commit Messages

```
fix(postprocess): TH0 — refresh predictive aggregates after every session
test(pipeline): TH1 — fix WS voice test + expand scenario coverage
test(pipeline): TH2 — text-injection drill runner + scenario YAML harness
test(pipeline): TH3 — audio fixture generation + stress_test --fixture-audio
test(api): TH4 — API integration test suite for manager, rep, and admin endpoints
```

---

## What You Can Do After This Suite

- **Catch voice pipeline regressions in seconds**: `pytest tests/test_ws_voice_pipeline.py`
- **Verify scenario behavior without speaking**: `python scripts/drill_runner.py --scenario scenarios/standard_close.yaml`
- **Run real Deepgram regression without speaking**: `python stress_test.py --fixture-audio`
- **Catch latency regressions before deploy**: `python stress_test.py --fixture-audio` (compares against baseline)
- **Verify all API endpoints are healthy**: `pytest tests/test_api_manager_integration.py`
