# PRD: Grading Engine V2
## Structured, Versioned, Auditable Grading

**Owner:** Engineering
**Status:** Ready for implementation
**Depends on:** Transcript Pipeline (PRD_TRANSCRIPT_PIPELINE) for structured turn access
**Feeds into:** Training Loop Infrastructure (PRD_TRAINING_LOOP) as labeled ground truth

---

## Problem Statement

The current grading system (`GradingService`) sends a flat prompt to Claude Opus and receives a JSON blob back. This works at small scale but fails the requirements of an ML-driven product:

- The prompt that produced a score is not stored — if Claude Opus changes behavior between versions, old scores become incomparable to new ones with no way to detect drift.
- `category_scores` in the `Scorecard` model is a JSON column storing `{score, rationale, evidence_turn_ids}` per category. The `rationale` is unstructured prose — no machine-readable signal for training.
- `evidence_turn_ids` is a flat list on the scorecard, not linked per-category to the turns that drove each score. You cannot ask "why was objection_handling 4.2?" and trace it to specific turns.
- There is no confidence interval on grades. A 30-turn session with a clean objection arc should produce a higher-confidence score than a 4-turn session.
- Manager overrides are stored as `override_score` on `ManagerReview`, but there is no alert when the override delta is large (which signals either a bad AI grade or a miscalibrated manager).
- `PromptVersion` rows exist in the DB but `GradingService` never reads them — it hardcodes the prompt at runtime.

---

## Goals

1. Wire `PromptVersion` at runtime so every scorecard records exactly which prompt produced it.
2. Upgrade `category_scores` schema to include structured rationale fields (not just prose), confidence intervals, and per-category evidence turn IDs.
3. Detect high-delta manager overrides in real time and surface them as calibration events.
4. Create a `GradingRun` fact table that makes every grading attempt auditable and replayable.
5. Lay the foundation for A/B testing prompt versions (phase 2 of Training Loop).

---

## Non-Goals

- This PRD does NOT build the A/B routing logic (that's Training Loop V1).
- This PRD does NOT change the underlying AI judge (still Claude Opus/claude-opus-4-5) — it only changes how we structure its input and output.
- This PRD does NOT train any models — it creates the labeled data those models will consume.

---

## Architecture

### 1. New Model: `GradingRun`

Add to `backend/app/models/grading.py` (new file):

```python
class GradingRun(Base, TimestampMixin):
    """One grading attempt — either live or a replay re-grade."""
    __tablename__ = "grading_runs"
    __table_args__ = (
        Index("ix_grading_runs_session_created", "session_id", "created_at"),
        Index("ix_grading_runs_prompt_version_created", "prompt_version_id", "created_at"),
    )

    id: str                       # uuid
    session_id: str               # FK sessions.id
    scorecard_id: str | None      # FK scorecards.id — null while grading is in flight
    prompt_version_id: str        # FK prompt_versions.id — the exact prompt used
    model_name: str               # e.g. "claude-opus-4-5-20251101"
    model_latency_ms: int
    input_token_count: int | None
    output_token_count: int | None
    status: str                   # "success" | "llm_error" | "parse_error" | "fallback_used"
    raw_llm_response: str | None  # full JSON string from Claude, stored for audit
    parse_error: str | None
    overall_score: float | None
    confidence_score: float       # 0.0–1.0, computed deterministically (see below)
    started_at: datetime
    completed_at: datetime | None
```

### 2. Upgraded `category_scores` Schema

Today `category_scores` is a flat dict: `{"opening": 8.1, "pitch_delivery": 5.2, ...}`.

Replace with structured per-category objects. Update `StructuredScorecardPayload` in `backend/app/schemas/scorecard.py`:

```python
class CategoryScoreV2(BaseModel):
    score: float                        # 0.0–10.0
    confidence: float                   # 0.0–1.0 — how much evidence drove this category
    rationale_summary: str              # ≤80 chars, machine-readable topic sentence
    rationale_detail: str               # full prose explanation for manager display
    evidence_turn_ids: list[str]        # turn IDs from THIS category's evidence (not global)
    behavioral_signals: list[str]       # e.g. ["acknowledged_objection", "price_anchor"]
    improvement_target: str | None      # specific, actionable next step (≤60 chars)

class StructuredScorecardPayloadV2(BaseModel):
    overall_score: float
    category_scores: dict[str, CategoryScoreV2]
    highlights: list[HighlightItem]
    ai_summary: str
    weakness_tags: list[str]
    evidence_quality: str               # "strong" | "moderate" | "weak" — overall evidence signal
    session_complexity: int             # 1–5, inferred from turn count + objection depth
```

**Migration:** The `Scorecard.category_scores` column is already JSON — no schema migration needed. Add a `scorecard_schema_version: str` column to `Scorecard` (default `"v1"`) so the dashboard can render the right component.

### 3. Confidence Interval Computation

Confidence is computed **deterministically** (no LLM needed) based on observable session properties. Add to `GradingService`:

```python
def compute_confidence(self, session: DrillSession, grading: dict) -> float:
    """
    Returns 0.0–1.0. Factors:
    - Turn count: <4 turns → 0.3 max. 4–10 → up to 0.7. 10+ → up to 1.0
    - Evidence density: evidence_turn_ids count / total rep turns
    - Objection coverage: objection turns with scores / total objection turns
    - Session completion: whether session reached close_attempt stage
    - Parse quality: whether all category_scores are present and within 0–10
    """
    rep_turns = [t for t in session.turns if t.speaker.value == "rep"]
    evidence_ids = set(grading.get("evidence_turn_ids", []))

    turn_factor = min(1.0, len(rep_turns) / 10.0)
    evidence_density = len(evidence_ids) / max(1, len(rep_turns))
    categories_present = len([k for k, v in grading.get("category_scores", {}).items()
                               if isinstance(v, dict) and 0 <= v.get("score", -1) <= 10])
    category_factor = categories_present / 5.0

    return round(min(1.0, (turn_factor * 0.4) + (evidence_density * 0.35) + (category_factor * 0.25)), 3)
```

### 4. Prompt Versioning at Runtime

**Current state:** `GradingPromptBuilder.build()` hardcodes the prompt.

**Change:** At service init, load the active grading prompt from `prompt_versions`:

```python
class GradingService:
    def __init__(self):
        self.settings = get_settings()
        self._active_prompt_version_id: str | None = None

    def _get_active_prompt_version(self, db: Session) -> PromptVersion | None:
        return db.scalar(
            select(PromptVersion)
            .where(PromptVersion.prompt_type == "grading_v2")
            .where(PromptVersion.active == True)
            .order_by(PromptVersion.created_at.desc())
        )
```

When `grade_session` is called, it looks up the active prompt, falls back to the hardcoded template if none is found, and records the `prompt_version_id` on the `GradingRun` row.

**Seeding:** Add a Alembic migration data seed that inserts the current hardcoded grading prompt as `PromptVersion(prompt_type="grading_v2", version="1.0.0", active=True)`.

### 5. Disagreement Detection (Override Delta Alert)

When a manager submits an override via `POST /manager/scorecards/{scorecard_id}/review`, check the delta:

```python
# In ManagerActionService.submit_review():
DISAGREEMENT_THRESHOLD = 2.0   # points on 0–10 scale

if override_score is not None and ai_score is not None:
    delta = abs(override_score - ai_score)
    if delta >= DISAGREEMENT_THRESHOLD:
        # Create an AnalyticsFactAlert with kind="grading_disagreement"
        # Include: session_id, scorecard_id, ai_score, override_score, delta,
        #          reviewer_id, prompt_version_id from the GradingRun
        _emit_disagreement_alert(db, review, scorecard, grading_run, delta)
```

The alert surfaces in the manager dashboard under a new "Calibration" tab (Phase M2 of the Manager Intelligence work). At sufficient volume, disagreement alerts become the primary signal for Training Loop prompt refinement.

### 6. Scorecard V1 → V2 Backfill Strategy

Do NOT run a batch re-grade of historical sessions on deploy. Instead:

- Any session graded after the deploy date uses V2 schema.
- Older scorecards retain `schema_version = "v1"` and the dashboard renders a legacy view.
- A background `CeleryTask` (`backfill_grading_v2`) can be triggered manually by admins for specific org_ids when needed. It re-grades sessions oldest-first, 50 at a time, and writes new `GradingRun` + upgraded `Scorecard`.

---

## Implementation Phases

### Phase G1: GradingRun table + prompt wiring (do first)
- Add `GradingRun` model and migration
- Wire `prompt_version_id` into `GradingService.grade_session()`
- Store `raw_llm_response` on `GradingRun`
- Add `scorecard_schema_version` column to `Scorecard` (migration)
- Seed the current hardcoded prompt as `PromptVersion` record
- Tests: `test_grading_run_is_created.py`, `test_prompt_version_is_loaded.py`

### Phase G2: V2 category schema + confidence
- Update `StructuredScorecardPayloadV2` schema
- Update `GradingPromptBuilder` to request `CategoryScoreV2` shape
- Implement `compute_confidence()` in `GradingService`
- Store confidence on `GradingRun.confidence_score` and per-category in `Scorecard.category_scores`
- Tests: `test_category_score_v2_schema.py`, `test_confidence_computation.py`

### Phase G3: Disagreement detection
- Add `DISAGREEMENT_THRESHOLD` check in `ManagerActionService.submit_review()`
- Emit `AnalyticsFactAlert(kind="grading_disagreement")`
- `GET /manager/analytics/calibration` endpoint returns disagreement events for the manager
- Tests: `test_disagreement_alert_emitted_on_high_delta.py`

---

## Key Files to Modify

```
backend/app/models/grading.py          — NEW: GradingRun model
backend/app/models/scorecard.py        — ADD: scorecard_schema_version column
backend/app/schemas/scorecard.py       — ADD: CategoryScoreV2, StructuredScorecardPayloadV2
backend/app/services/grading_service.py — MODIFY: prompt wiring, confidence, GradingRun writes
backend/app/services/manager_action_service.py — MODIFY: disagreement detection on review
backend/app/api/manager.py             — ADD: GET /manager/analytics/calibration
backend/alembic/versions/              — NEW: migration for grading_runs table, schema_version col
```

---

## Success Metrics

- Every scorecard written after deploy has a corresponding `GradingRun` row.
- `GradingRun.prompt_version_id` is non-null for 100% of post-deploy grades.
- `Scorecard.category_scores` contains `evidence_turn_ids` per category (not global).
- Disagreement alerts fire within 60s of a high-delta override being submitted.
- No regression on existing scorecard API tests.
