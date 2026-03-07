# DoorDrill Infrastructure PRD Suite
## Intelligence Layer: Grading, Warehouse, Training Loop, Transcript Pipeline

**Version:** 1.0
**Status:** Ready for Codex implementation
**Architecture context:** See `IMPLEMENTATION_SPEC.md` and `SYSTEM_ARCHITECTURE_ANALYSIS.md` at repo root

---

## Why These Four PRDs Form a System

These are not independent features. They are a single data flywheel where each layer feeds the next:

```
Rep drills
    ↓
[TRANSCRIPT PIPELINE]  — structured storage of every turn, emotion, objection, micro-behavior
    ↓
[GRADING ENGINE V2]    — versioned, auditable, per-category grades with confidence + evidence
    ↓
[DATA WAREHOUSE]       — star schema aggregations that make the manager dashboard fast at scale
    ↓
[TRAINING LOOP]        — manager overrides become labeled data, prompt A/B tests promote winners,
                          adaptive difficulty tunes from outcome feedback
    ↓
Better simulations → More realistic drills → More data → (repeat)
```

Build in this order. Each PRD has the right dependencies listed.

---

## PRD Catalog

| PRD | File | Build Order | Key Output |
|-----|------|-------------|------------|
| Transcript Pipeline | `PRD_TRANSCRIPT_PIPELINE.md` | 1st | Structured turn + event data for all downstream systems |
| Grading Engine V2 | `PRD_GRADING_ENGINE_V2.md` | 2nd | Versioned, auditable scorecards with per-category confidence |
| Data Warehouse Layer | `PRD_DATA_WAREHOUSE_LAYER.md` | 3rd | Star schema powering fast dashboard queries at scale |
| Training Loop | `PRD_TRAINING_LOOP.md` | 4th | Override labels → A/B prompt testing → adaptive difficulty tuning |

---

## Codex Execution Guide

Each PRD is self-contained and written for Codex to implement end-to-end. Use the following bootstrap workflow for each phase.

### Step 1 — Bootstrap context (paste first in every new Codex thread)

Paste the contents of `Daily Workflows/3:6/BOOTSTRAP_PROMPT.md` before any phase prompt.

### Step 2 — Run phases in order within each PRD

Each PRD defines numbered phases (e.g., `Phase TP1`, `Phase TP2`). Always complete phase N before starting phase N+1 within a PRD. PRDs themselves should also be run sequentially (Transcript Pipeline before Grading Engine before Warehouse before Training Loop).

### Step 3 — Verify before moving on

After each phase, run:
```bash
cd backend
python -m pytest tests/ -x -q
```
All tests must pass before the next phase. If a test fails, fix it in the same Codex thread before moving on.

### Step 4 — Commit after each phase

Each completed phase should be its own commit with a clear message:
```
feat(transcript): TP1 — enriched session_turns columns + TurnEnrichmentService skeleton
feat(grading): G1 — GradingRun table + prompt version wiring
feat(warehouse): W1 — star schema + WarehouseEtlService
feat(training): T1 — OverrideLabel capture on manager review
```

---

## Paste-Ready Phase Prompts

Copy the prompt for the phase you want to run and paste it after the bootstrap in Codex.

---

### PHASE TP1 — Transcript Pipeline: Enriched turn columns

```
Bootstrap is loaded above. Implement Phase TP1 from PRD_TRANSCRIPT_PIPELINE.md.

Goals:
1. Add the new nullable columns to session_turns via Alembic migration:
   emotion_before, emotion_after, emotion_changed, resistance_level, objection_pressure,
   active_objections, queued_objections, mb_tone, mb_sentence_length, mb_behaviors,
   mb_interruption_type, mb_realism_score, mb_opening_pause_ms, mb_total_pause_ms,
   behavioral_signals, was_graded, evidence_for_categories, is_high_quality
2. Create backend/app/services/turn_enrichment_service.py with TurnEnrichmentService class.
   Implement enrich_session() and _reconstruct_state_timeline() — replay session_events
   in order to extract emotion/stage/objection_pressure snapshots per turn.
3. Wire TurnEnrichmentService into SessionPostprocessService.run() after the grading step.
4. Write test_turn_enrichment.py with test_turn_enrichment_populates_emotion_columns.
   Seed a session with known session_events, run enrichment, assert turn columns populated.
5. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE TP2 — Transcript Pipeline: fact_turn_events

```
Bootstrap is loaded above. Phase TP1 is complete. Implement Phase TP2 from PRD_TRANSCRIPT_PIPELINE.md.

Goals:
1. Create FactTurnEvent model in backend/app/models/transcript.py and Alembic migration.
2. Implement _write_fact_turn_events() in TurnEnrichmentService.
   Write rows for all 12 EVENT_TYPES defined in the PRD.
3. Add tests: test_fact_turn_events_written_for_session.py — verify all key event types
   are written for a seeded test session (emotion_transition, objection_surfaced, etc).
4. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE TP3 — Transcript Pipeline: Objection taxonomy

```
Bootstrap is loaded above. Phase TP2 is complete. Implement Phase TP3.

Goals:
1. Create ObjectionType model in backend/app/models/transcript.py. Add migration.
2. Write a migration data seed with the full D2D pest control objection taxonomy
   (price, price_per_month, incumbent_provider, locked_in_contract, timing, not_right_now,
   trust, skeptical_of_product, need, decision_authority — see PRD for full list).
3. Add GET /scenarios/objection-types endpoint in backend/app/api/scenarios.py.
   Returns all active ObjectionType rows for the org (or system defaults).
4. Tests: test_objection_taxonomy_seed.py, test_objection_types_endpoint.py.
5. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE G1 — Grading Engine V2: GradingRun + prompt wiring

```
Bootstrap is loaded above. Implement Phase G1 from PRD_GRADING_ENGINE_V2.md.

Goals:
1. Create GradingRun model in backend/app/models/grading.py. Add Alembic migration.
2. Add scorecard_schema_version column to Scorecard model. Migration (default "v1").
3. Modify GradingService.grade_session() to:
   a. Load the active PromptVersion for prompt_type="grading_v2" at start of grading.
   b. Fall back to the hardcoded template if no active version exists.
   c. Write a GradingRun row capturing: session_id, prompt_version_id, model_name,
      model_latency_ms, input/output token counts, status, raw_llm_response, overall_score.
   d. Link GradingRun.scorecard_id after scorecard write.
4. Write a migration that seeds the current hardcoded grading prompt as:
   PromptVersion(prompt_type="grading_v2", version="1.0.0", active=True, content=<current prompt>).
5. Tests: test_grading_run_is_created.py, test_prompt_version_is_loaded.py.
6. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE G2 — Grading Engine V2: V2 category schema + confidence

```
Bootstrap is loaded above. Phase G1 is complete. Implement Phase G2.

Goals:
1. Add CategoryScoreV2 and StructuredScorecardPayloadV2 to backend/app/schemas/scorecard.py.
   Fields per-category: score, confidence, rationale_summary, rationale_detail,
   evidence_turn_ids, behavioral_signals, improvement_target.
2. Update GradingPromptBuilder to request CategoryScoreV2 shape from Claude.
3. Implement GradingService.compute_confidence() — deterministic 0.0–1.0 computation
   from turn count, evidence density, category completeness.
4. Store confidence on GradingRun.confidence_score and per-category in category_scores.
5. Set scorecard_schema_version="v2" on newly written scorecards.
6. Tests: test_category_score_v2_schema.py, test_confidence_computation.py.
7. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE G3 — Grading Engine V2: Disagreement detection

```
Bootstrap is loaded above. Phase G2 is complete. Implement Phase G3.

Goals:
1. Add DISAGREEMENT_THRESHOLD = 2.0 check in ManagerActionService.submit_review().
   When abs(override_score - ai_score) >= 2.0, emit AnalyticsFactAlert with
   kind="grading_disagreement", metadata including session_id, scorecard_id,
   ai_score, override_score, delta, reviewer_id, prompt_version_id.
2. Add GET /manager/analytics/calibration endpoint in backend/app/api/manager.py.
   Returns recent grading_disagreement alerts for this manager's org, sorted by delta desc.
3. Tests: test_disagreement_alert_emitted_on_high_delta.py.
4. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE W1 — Data Warehouse: Star schema + ETL skeleton

```
Bootstrap is loaded above. Implement Phase W1 from PRD_DATA_WAREHOUSE_LAYER.md.

Goals:
1. Create models in backend/app/models/warehouse.py:
   DimRep, DimScenario, DimTime, FactSession, FactRepDaily
   (see full column specs in PRD_DATA_WAREHOUSE_LAYER.md).
2. Alembic migration. Pre-populate dim_time for 2025–2030.
3. Create backend/app/services/warehouse_etl_service.py with WarehouseEtlService.
   Implement write_session() — idempotent upsert using session_id as conflict key.
   Call _upsert_dim_rep(), _upsert_dim_scenario(), _upsert_fact_session(), _upsert_fact_rep_daily().
4. Wire WarehouseEtlService.write_session() into SessionPostprocessService.run()
   as the final step after grading.
5. Tests: test_warehouse_write_session.py — run write_session() twice on same session,
   assert exactly one fact_sessions row exists and columns match expected values.
6. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE W2 — Data Warehouse: Dimension updates on manager actions

```
Bootstrap is loaded above. Phase W1 is complete. Implement Phase W2.

Goals:
1. When a manager submits a review (ManagerActionService.submit_review()), update
   fact_sessions row: set has_manager_review=True, override_score, override_delta.
2. When a coaching note is created, set fact_sessions.has_coaching_note=True.
3. Tests: test_warehouse_update_on_review.py — verify fact_sessions is updated
   immediately after review submission.
4. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE W3 — Data Warehouse: Replace live analytics queries

```
Bootstrap is loaded above. Phase W2 is complete. Implement Phase W3.

Goals:
1. Add _use_warehouse flag to ManagementAnalyticsRuntimeService (default True when
   fact_sessions rows exist for the manager, else fall back to live queries).
2. Implement warehouse-backed methods for:
   - Team skill heatmap (query fact_rep_daily)
   - Score trend lines (query fact_sessions per rep)
   - Scenario pass rates (aggregate fact_sessions by scenario_id)
   - Score distribution histogram (SELECT overall_score from fact_sessions)
3. All existing test_management_analytics_runtime_track_f.py tests must still pass.
4. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE T1 — Training Loop: Override label capture

```
Bootstrap is loaded above. Implement Phase T1 from PRD_TRAINING_LOOP.md.

Goals:
1. Create OverrideLabel model in backend/app/models/training.py. Alembic migration.
2. In ManagerActionService.submit_review(), after writing ManagerReview, auto-create
   an OverrideLabel row if override_score is not None.
   Compute label_quality: high/medium/low based on delta and manager review count.
   Link to GradingRun via grading_run_id (look up most recent GradingRun for the session).
3. Tests: test_override_label_created_on_review.py — assert OverrideLabel row exists
   after review submission, quality field is correct for different delta values.
4. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE T2 — Training Loop: Prompt experiment infrastructure

```
Bootstrap is loaded above. Phase T1 is complete. Implement Phase T2.

Goals:
1. Create PromptExperiment model in backend/app/models/training.py. Migration.
2. Add deterministic routing in GradingService._select_prompt_version():
   hash(session_id) % 100 to route to control or challenger based on active experiment.
3. Create backend/app/services/prompt_experiment_service.py with:
   evaluate() — compute mean calibration error per arm from OverrideLabels.
   promote_winner() — set winning PromptVersion.active=True, mark experiment completed.
4. Add admin endpoints in backend/app/api/admin.py (new file):
   POST /admin/prompt-experiments, GET /admin/prompt-experiments/{id},
   POST /admin/prompt-experiments/{id}/evaluate,
   POST /admin/prompt-experiments/{id}/promote.
5. Tests: test_prompt_routing_is_deterministic.py, test_experiment_evaluation.py.
6. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE T3 — Training Loop: Adaptive loop closure

```
Bootstrap is loaded above. Phase T2 is complete. Implement Phase T3.

Goals:
1. Create AdaptiveRecommendationOutcome model in backend/app/models/training.py. Migration.
2. After grading completes in SessionPostprocessService, check if session came from an
   adaptive assignment (retry_policy has "adaptive_training" key). If so, write
   AdaptiveRecommendationOutcome with before/after skill_delta per focus skill.
3. In AdaptiveTrainingService.build_plan(), load recent outcomes for the rep and
   adjust recommended_difficulty if a skill/difficulty pair has success_rate < 40%
   (reduce difficulty by 1) or > 80% for 5+ sessions (increase by 1).
4. Tests: test_adaptive_outcome_written_after_session.py,
   test_difficulty_tunes_on_outcomes.py.
5. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE T4 — Training Loop: Training signal export

```
Bootstrap is loaded above. Phase T3 is complete. Implement Phase T4.

Goals:
1. Add GET /admin/training-signals/export endpoint in backend/app/api/admin.py.
   Query params: quality (high|medium|all), prompt_type, from_date, to_date, format (jsonl|json).
   Returns TrainingExample records per OverrideLabel row.
2. Each TrainingExample includes: input (transcript turns with enriched columns from
   Transcript Pipeline), ai_output (full CategoryScoreV2), human_correction (override data).
3. Set OverrideLabel.exported_at and export_batch_id on export.
4. Tests: test_training_signal_export_format.py — assert valid JSONL with required fields.
5. Run pytest tests/ -x -q. All tests must pass.
```

---

## Cross-PRD Dependencies Map

```
TP1 (enriched turns)
  └─→ TP2 (fact_turn_events)
        └─→ TP3 (objection taxonomy)
              └─→ TP4 (training export upgrade)

G1 (GradingRun + prompt wiring)
  └─→ G2 (V2 schema + confidence)
        └─→ G3 (disagreement detection)

W1 (star schema + ETL)
  └─→ W2 (dimension updates)
        └─→ W3 (replace live queries)

T1 (override labels)       ← requires G1 (GradingRun FK)
  └─→ T2 (prompt A/B)      ← requires G1 (routing)
        └─→ T3 (adaptive loop) ← requires TP1 (skill delta)
              └─→ T4 (export) ← requires TP1 (turn structure)
```

**Minimum viable sequence to get real training data flowing:**
`TP1 → G1 → G2 → T1 → T4`

Everything else is quality/scale infrastructure that can follow.
