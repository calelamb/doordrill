# PRD: Training Loop Infrastructure
## Closed Feedback Loop — Grading → Difficulty → Prompts → Models

**Owner:** Engineering
**Status:** Ready for implementation
**Depends on:** Grading Engine V2 (labeled data), Data Warehouse Layer (aggregate signals)
**Feeds into:** Adaptive Training Service (difficulty tuning), future fine-tuning runs

---

## Problem Statement

DoorDrill currently has several disconnected feedback signals that are never recycled back into the system:

- **Manager overrides** are stored in `manager_reviews` but never used to improve future grades. A manager who corrects the AI 50 times is teaching the system nothing.
- **Prompt versions** exist in the DB but there is no mechanism to test one prompt against another, measure which produces better-calibrated scores, and promote the winner.
- **Adaptive training** (`AdaptiveTrainingService`) recommends scenario difficulty from past scores — but there's no feedback path for "did the recommended difficulty actually produce improvement?" The recommendation engine is open-loop.
- **Weakness tags** from scorecards never propagate back to scenario difficulty tuning. A rep with chronic `objection_handling` weakness should automatically get objection-heavy scenarios promoted — but today a manager must do this manually.

The training loop is the moat. Every drill a rep takes, every grade Claude issues, every correction a manager makes should make the system smarter. This PRD builds that flywheel.

---

## Goals

1. Capture manager overrides as structured training labels (not just DB rows).
2. Build prompt A/B infrastructure: route a configurable % of grading runs to a challenger prompt, measure calibration vs. manager ground truth, promote winners.
3. Close the adaptive training loop: use grading outcomes to tune difficulty recommendations per rep-weakness pair.
4. Create a `TrainingSignal` export API that can seed future fine-tuning runs.

---

## Non-Goals

- This PRD does NOT train or fine-tune any model. It creates the infrastructure and labeled data that fine-tuning will consume (that's a future PRD).
- This PRD does NOT change the AI homeowner voice or simulation. It only touches the grading and recommendation layer.
- This PRD does NOT require Anthropic or OpenAI fine-tuning APIs to be wired yet.

---

## Architecture

### 1. Override-as-Label Capture

When a manager submits an override review today, `ManagerReview` stores:
- `override_score` (the manager's corrected overall score)
- `reason_code` (why they overrode)

**What's missing:** The manager's per-category corrections, and a structured link to the `GradingRun` that produced the AI score. Without per-category corrections, override data can only train an overall score adjustment, not teach the AI which specific judgment was wrong.

**New model: `OverrideLabel`** in `backend/app/models/training.py`:

```python
class OverrideLabel(Base, TimestampMixin):
    """
    Structured training label emitted when a manager overrides an AI grade.
    One row per scorecard review that includes at least one category correction.
    """
    __tablename__ = "override_labels"
    __table_args__ = (
        Index("ix_override_labels_grading_run", "grading_run_id"),
        Index("ix_override_labels_manager_created", "manager_id", "created_at"),
        Index("ix_override_labels_exported", "exported_at"),   -- for training export queries
    )

    id: str                    # uuid
    review_id: str             # FK manager_reviews.id (1-to-1)
    grading_run_id: str        # FK grading_runs.id — the specific grading attempt overridden
    session_id: str            # FK sessions.id
    manager_id: str            # FK users.id
    org_id: str

    # AI grades (snapshot at override time, denormalized for training export)
    ai_overall_score: float
    ai_category_scores: dict   # full CategoryScoreV2 JSON

    # Manager corrections
    override_overall_score: float | None
    override_category_scores: dict | None  # partial — only categories the manager changed
    override_reason_text: str | None       # free-text note if manager wrote one
    override_delta_overall: float          # abs(override - ai)
    is_high_disagreement: bool             # True if delta >= DISAGREEMENT_THRESHOLD

    # Training metadata
    label_quality: str         # "high" | "medium" | "low"
    exported_at: datetime | None  -- set when included in a training export
    export_batch_id: str | None
```

**Label quality rules:**
- `high`: override_delta_overall >= 2.0 AND manager has reviewed >= 10 sessions (calibrated manager)
- `medium`: override_delta_overall >= 1.0
- `low`: override_delta_overall < 1.0 OR manager has reviewed < 3 sessions

**Integration:** In `ManagerActionService.submit_review()`, after writing `ManagerReview`, auto-create an `OverrideLabel` row if `override_score is not None`.

---

### 2. Prompt A/B Infrastructure

The `PromptVersion` table already exists. The grading service needs routing logic.

**New model: `PromptExperiment`** in `backend/app/models/training.py`:

```python
class PromptExperiment(Base, TimestampMixin):
    """
    An A/B test between two prompt versions for a given prompt_type.
    Active experiment = route `challenger_traffic_pct`% of grading runs
    to the challenger, the rest to the control.
    """
    __tablename__ = "prompt_experiments"

    id: str
    prompt_type: str            # "grading_v2"
    control_version_id: str     # FK prompt_versions.id
    challenger_version_id: str  # FK prompt_versions.id
    challenger_traffic_pct: int # 0–100. Start at 10.
    status: str                 # "active" | "paused" | "completed" | "rolled_back"
    started_at: datetime
    ended_at: datetime | None
    winner: str | None          # "control" | "challenger" | "inconclusive"

    # Outcome metrics (computed by PromptExperimentService.evaluate())
    control_mean_calibration_error: float | None
    challenger_mean_calibration_error: float | None
    control_session_count: int
    challenger_session_count: int
    p_value: float | None
    min_sessions_for_decision: int  # default 200
```

**Routing in `GradingService`:**

```python
def _select_prompt_version(self, db: Session) -> PromptVersion:
    experiment = db.scalar(
        select(PromptExperiment)
        .where(PromptExperiment.prompt_type == "grading_v2")
        .where(PromptExperiment.status == "active")
    )
    if experiment is None:
        return self._get_active_prompt_version(db)

    # Deterministic routing: hash(session_id) % 100 < challenger_traffic_pct
    import hashlib
    bucket = int(hashlib.md5(self.current_session_id.encode()).hexdigest(), 16) % 100
    if bucket < experiment.challenger_traffic_pct:
        return db.get(PromptVersion, experiment.challenger_version_id)
    return db.get(PromptVersion, experiment.control_version_id)
```

Deterministic routing (not random) means: re-grading the same session always uses the same prompt, making comparison fair and auditable.

**Calibration error metric:** For each grading run in the experiment, after manager reviews accumulate:
```
calibration_error = |ai_score - manager_override_score|
```
A lower mean calibration error means the prompt produces scores closer to what calibrated managers actually believe. Winner is whichever version has lower mean calibration error after `min_sessions_for_decision` sessions.

**`PromptExperimentService`:**
```python
class PromptExperimentService:
    def evaluate(self, db: Session, experiment_id: str) -> None:
        """
        Computes mean calibration error for control and challenger.
        If min_sessions reached and p_value < 0.05, promotes winner.
        """

    def promote_winner(self, db: Session, experiment_id: str) -> None:
        """
        Sets winning PromptVersion.active = True,
        deactivates loser, marks experiment.status = "completed".
        """
```

**Admin endpoints** (manager role required, org admin flag):
- `POST /admin/prompt-experiments` — create experiment
- `GET /admin/prompt-experiments/{id}` — current metrics
- `POST /admin/prompt-experiments/{id}/evaluate` — trigger evaluation
- `POST /admin/prompt-experiments/{id}/promote` — manually promote winner

---

### 3. Closing the Adaptive Training Loop

`AdaptiveTrainingService.build_plan()` currently recommends scenarios based on past skill scores alone. It doesn't track whether its recommendations actually worked.

**New feedback table: `AdaptiveRecommendationOutcome`**:

```python
class AdaptiveRecommendationOutcome(Base, TimestampMixin):
    """
    Tracks whether an adaptive training recommendation produced skill improvement.
    Written after the recommended session is graded.
    """
    __tablename__ = "adaptive_recommendation_outcomes"

    id: str
    assignment_id: str      # FK assignments.id — the adaptive assignment
    session_id: str | None  # FK sessions.id — the completed session
    rep_id: str
    manager_id: str
    recommended_scenario_id: str
    recommended_difficulty: int
    recommended_focus_skills: list[str]

    # Pre-recommendation baseline
    baseline_skill_scores: dict   # {skill: score} at recommendation time
    baseline_overall_score: float | None

    # Post-session outcomes (written after grading)
    outcome_skill_scores: dict | None   # {skill: score} after session
    outcome_overall_score: float | None
    skill_delta: dict | None            # {skill: delta} for each focus skill
    recommendation_success: bool | None # True if avg focus skill delta >= +0.5

    outcome_written_at: datetime | None
```

**Writing outcomes:** When `SessionPostprocessService` completes grading, check if the session came from an adaptive assignment. If so, write `AdaptiveRecommendationOutcome` with the before/after skill deltas.

**Tuning difficulty from outcomes:** Add to `AdaptiveTrainingService.build_plan()`:

```python
def _load_recommendation_outcomes(self, db: Session, rep_id: str) -> list[dict]:
    """
    Load recent recommendation outcomes for this rep.
    If a skill/difficulty pair has recommendation_success=False 3+ times,
    reduce recommended_difficulty for that skill by 1.
    If success rate > 80% for 5+ sessions, increase difficulty by 1.
    """
```

This creates a second-order feedback loop: difficulty recommendations become rep-specific and calibrate over time.

---

### 4. Training Signal Export API

An export endpoint that serializes labeled training data for future fine-tuning.

```
GET /admin/training-signals/export
  ?quality=high                    # high | medium | all
  ?prompt_type=grading_v2
  ?from_date=2026-01-01
  ?to_date=2026-03-31
  ?format=jsonl                    # jsonl | json
```

Each record in the export is a `TrainingExample`:
```json
{
  "input": {
    "transcript": [...],
    "prompt_version": "2.0.0",
    "scenario": {...}
  },
  "ai_output": {
    "overall_score": 6.1,
    "category_scores": {...},
    "ai_summary": "..."
  },
  "human_correction": {
    "override_overall_score": 8.0,
    "override_category_scores": {"objection_handling": {"score": 7.5}},
    "delta": 1.9,
    "manager_id": "...",
    "label_quality": "high"
  }
}
```

This is the exact format needed for supervised fine-tuning of a smaller grading judge model later. Export sets `OverrideLabel.exported_at` and `export_batch_id` so you can track what's been used in training.

---

## Implementation Phases

### Phase T1: Override labels
- Add `OverrideLabel` model + migration
- Wire `OverrideLabel` creation in `ManagerActionService.submit_review()`
- Tests: `test_override_label_created_on_review.py`

### Phase T2: Prompt experiment infrastructure
- Add `PromptExperiment` model + migration
- Add routing logic in `GradingService._select_prompt_version()`
- Implement `PromptExperimentService` (evaluate + promote)
- Admin endpoints
- Tests: `test_prompt_routing_is_deterministic.py`, `test_experiment_evaluation.py`

### Phase T3: Adaptive loop closure
- Add `AdaptiveRecommendationOutcome` model + migration
- Write outcomes in `SessionPostprocessService` after grading
- Integrate outcome history into `AdaptiveTrainingService.build_plan()`
- Tests: `test_adaptive_outcome_written_after_session.py`, `test_difficulty_tunes_on_outcomes.py`

### Phase T4: Training signal export
- `GET /admin/training-signals/export` endpoint
- JSONL serialization
- `exported_at` tracking on `OverrideLabel`
- Tests: `test_training_signal_export_format.py`

---

## Key Files

```
backend/app/models/training.py               — NEW: OverrideLabel, PromptExperiment, AdaptiveRecommendationOutcome
backend/app/services/prompt_experiment_service.py — NEW
backend/app/services/manager_action_service.py    — MODIFY: emit OverrideLabel on review
backend/app/services/grading_service.py           — MODIFY: A/B routing
backend/app/services/session_postprocess_service.py — MODIFY: write AdaptiveRecommendationOutcome
backend/app/services/adaptive_training_service.py — MODIFY: consume outcome history
backend/app/api/admin.py                          — NEW: experiment + export endpoints
backend/alembic/versions/                         — NEW: training tables migration
```

---

## Success Metrics

- Every manager override creates an `OverrideLabel` row within 1s.
- Prompt experiments route traffic deterministically (same session_id → same prompt 100% of the time).
- After 200 labeled sessions per experiment arm, winner is auto-identified.
- Adaptive difficulty recommendations improve by >= 10% accuracy after 50 feedback cycles (measured by recommendation_success rate).
- Training export produces valid JSONL loadable by the Anthropic fine-tuning API format.
