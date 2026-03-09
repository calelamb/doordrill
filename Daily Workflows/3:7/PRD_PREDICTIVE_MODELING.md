# PRD: Predictive Modeling Layer
**DoorDrill — Engineering Spec**
Date: 2026-03-08
Phases: PM1 → PM2 → PM3 → PM4 → PM5 → PM6

---

## Context & Philosophy

DoorDrill already collects rich longitudinal data: per-session category scores, adaptive recommendation outcomes, manager override labels, warehouse daily rollups, and hire cohort metadata. The predictive modeling layer turns this historical record into forward-looking signals — answering not just "how is this rep doing?" but "where will they be in 30 days, and what should the manager do about it right now?"

All predictive features are **additive and zero-regression**: every new signal is an enrichment on top of existing endpoints. If no historical data exists for a rep, all predictive fields gracefully return `null` or are omitted.

All models are stored in PostgreSQL (Supabase). No external ML infrastructure is needed — numpy/scipy for regression, sqlalchemy for queries. No PyTorch, no scikit-learn dependency in Phase 1–4.

---

## Data Available for Modeling

| Source | Key fields |
|---|---|
| `fact_sessions` | `overall_score`, `score_opening`, `score_pitch_delivery`, `score_objection_handling`, `score_closing_technique`, `score_professionalism`, `session_date`, `rep_id` |
| `fact_rep_daily` | `avg_score`, `session_count`, `avg_objection_handling`, `avg_closing_technique`, `session_date`, `rep_id` |
| `adaptive_recommendation_outcomes` | `recommendation_success`, `skill_delta`, `recommended_focus_skills`, `recommended_difficulty`, `baseline_skill_scores`, `outcome_skill_scores` |
| `override_labels` | `override_delta_overall`, `ai_category_scores`, `override_category_scores`, `is_high_disagreement` |
| `dim_reps` | `hire_cohort`, `industry`, `first_session_at`, `total_sessions` |
| `AdaptiveTrainingService.build_plan()` | `skill_profile`, `readiness_score`, `weakest_skills`, `performance_trend` |
| `AdaptiveTrainingService._compute_readiness_trajectory()` | Per-skill linear regression slope, sessions-to-readiness estimate |

---

## Phase PM1 — Skill Velocity & Readiness Forecasting

### Goal
Persist structured readiness forecasts per rep to the database, enrich the `/adaptive-plan` response with velocity metrics and projected readiness dates, and expose a standalone `/forecast/{rep_id}` endpoint for the frontend.

Currently `_compute_readiness_trajectory()` computes a linear regression slope per skill and projects sessions-to-readiness on the fly but never persists it. PM1 lifts this into a first-class `PredictiveModelingService`, adds a `rep_skill_forecasts` table, and writes updated forecasts whenever `build_plan()` is called.

### New Model: `RepSkillForecast`

```python
# backend/app/models/predictive.py (new file)

class RepSkillForecast(Base, TimestampMixin):
    __tablename__ = "rep_skill_forecasts"
    __table_args__ = (
        UniqueConstraint("rep_id", "skill", name="uq_rep_skill_forecast_rep_skill"),
        Index("ix_rep_skill_forecasts_rep", "rep_id"),
        Index("ix_rep_skill_forecasts_org", "org_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    skill: Mapped[str] = mapped_column(String(64), nullable=False)               # e.g. "objection_handling"
    current_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    velocity: Mapped[float | None] = mapped_column(Float, nullable=True)          # score improvement per session
    sessions_to_readiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    projected_ready_at_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)  # absolute session number
    readiness_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=7.0)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # sessions used in regression
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)         # regression quality
    forecast_computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

### New Service: `PredictiveModelingService`

**File:** `backend/app/services/predictive_modeling_service.py`

```python
class PredictiveModelingService:

    READINESS_THRESHOLD = 7.0
    MIN_SESSIONS_FOR_REGRESSION = 3

    def compute_and_persist_forecast(
        self, db: Session, *, rep_id: str, org_id: str, skill_profile: list[dict]
    ) -> list[dict]:
        """
        Called by AdaptiveTrainingService.build_plan() after building skill_profile.
        Runs linear regression per skill, upserts RepSkillForecast rows.
        Returns list of forecast dicts to embed in plan response.
        """

    def _linear_regression(self, x: list[float], y: list[float]) -> tuple[float, float, float]:
        """Returns (slope, intercept, r_squared). Uses numpy.polyfit."""

    def get_rep_forecast(self, db: Session, *, rep_id: str) -> dict:
        """
        Returns full forecast for a rep:
        {
          rep_id, readiness_score, overall_velocity, overall_sessions_to_readiness,
          skill_forecasts: [{ skill, current_score, velocity, sessions_to_readiness, r_squared }],
          forecast_computed_at
        }
        """

    def get_team_forecast(self, db: Session, *, manager_id: str, org_id: str) -> dict:
        """
        Aggregates rep forecasts for all active reps under manager.
        {
          manager_id, team_size,
          avg_sessions_to_readiness, median_sessions_to_readiness,
          reps_already_ready: int,       # readiness_score >= threshold
          reps_on_track: int,            # positive velocity, sessions_to_readiness <= 20
          reps_at_risk: int,             # negative velocity OR sessions_to_readiness > 30
          rep_summaries: [{ rep_id, name, readiness_score, sessions_to_readiness, velocity }]
        }
        """
```

### Integration Points
- `AdaptiveTrainingService.build_plan()` calls `predictive_service.compute_and_persist_forecast()` after computing skill_profile.
- Plan response gains new top-level key: `"readiness_forecast": [...]`
- `_compute_readiness_trajectory()` in `AdaptiveTrainingService` is deprecated in favor of `PredictiveModelingService`.

### New API Endpoints
```
GET  /api/v1/reps/{rep_id}/forecast          → RepSkillForecast data for a single rep
GET  /api/v1/managers/{manager_id}/team-forecast → Aggregated team readiness forecast
```

### Alembic Migration
`20260308_0022_predictive_skill_forecasts.py` — creates `rep_skill_forecasts` table with unique constraint on `(rep_id, skill)`.

---

### Codex Prompt — PM1

```
Implement Phase PM1 of the Predictive Modeling layer for DoorDrill.

**New file: backend/app/models/predictive.py**
Create a RepSkillForecast SQLAlchemy model:
- Table: rep_skill_forecasts
- Columns: id (String PK), rep_id (FK users.id CASCADE), org_id (FK organizations.id CASCADE),
  skill (String 64), current_score (Float nullable), velocity (Float nullable),
  sessions_to_readiness (Integer nullable), projected_ready_at_sessions (Integer nullable),
  readiness_threshold (Float default 7.0), sample_size (Integer default 0),
  r_squared (Float nullable), forecast_computed_at (DateTime timezone=True)
- Unique constraint on (rep_id, skill)
- Indexes: ix_rep_skill_forecasts_rep on rep_id, ix_rep_skill_forecasts_org on org_id
- Include TimestampMixin and _uuid() helper
Import this model in backend/app/models/__init__.py.

**New file: backend/app/services/predictive_modeling_service.py**
Class PredictiveModelingService:

READINESS_THRESHOLD = 7.0
MIN_SESSIONS_FOR_REGRESSION = 3

Method compute_and_persist_forecast(db, *, rep_id, org_id, skill_profile: list[dict]) -> list[dict]:
  - skill_profile is the list of dicts from AdaptiveTrainingService.build_plan(), each having
    {"skill": str, "score": float, "history": list[float]}
  - For each skill, run _linear_regression on enumerate(history) → (x=session_index, y=scores)
  - If len(history) < MIN_SESSIONS_FOR_REGRESSION, set velocity/sessions_to_readiness to None
  - sessions_to_readiness = ceil((READINESS_THRESHOLD - current_score) / velocity) if velocity > 0 else None
  - Upsert RepSkillForecast row using INSERT ... ON CONFLICT DO UPDATE (or SQLAlchemy merge)
  - Return list of forecast dicts: [{skill, current_score, velocity, sessions_to_readiness, r_squared}]

Method _linear_regression(x, y) -> tuple[float, float, float]:
  - Use numpy.polyfit(x, y, 1) for slope and intercept
  - Compute r_squared = 1 - (ss_res / ss_tot) where ss_res = sum((y - y_hat)^2), ss_tot = sum((y - mean(y))^2)
  - Return (slope, intercept, r_squared)

Method get_rep_forecast(db, *, rep_id) -> dict:
  - Query all RepSkillForecast rows for rep_id
  - Compute overall_velocity = mean of per-skill velocities
  - Compute overall_sessions_to_readiness = max of per-skill sessions_to_readiness (slowest skill gates readiness)
  - Return {rep_id, skill_forecasts: [...], overall_velocity, overall_sessions_to_readiness, forecast_computed_at}

Method get_team_forecast(db, *, manager_id, org_id) -> dict:
  - Query DimRep for all is_active=True reps under manager_id in org_id
  - For each rep, call get_rep_forecast
  - Categorize: reps_already_ready (readiness_score >= 7.0), reps_on_track (velocity > 0 and sessions_to_readiness <= 20),
    reps_at_risk (velocity <= 0 OR sessions_to_readiness > 30 OR sessions_to_readiness is None)
  - Return aggregated dict

**Modify: backend/app/services/adaptive_training_service.py**
- Import PredictiveModelingService at top
- At the end of build_plan(), after computing skill_profile, call:
    forecasts = PredictiveModelingService().compute_and_persist_forecast(
        db, rep_id=rep_id, org_id=<rep.org_id>, skill_profile=plan["skill_profile"]
    )
  - Append "readiness_forecast": forecasts to the returned plan dict
- Deprecate _compute_readiness_trajectory() — keep it but have it delegate to PredictiveModelingService

**New file: backend/alembic/versions/20260308_0022_predictive_skill_forecasts.py**
- Create rep_skill_forecasts table with all columns above
- Include unique constraint and indexes

**New API endpoints in backend/app/api/v1/reps.py (or new router):**
  GET /api/v1/reps/{rep_id}/forecast
    - Auth: manager or the rep themselves
    - Returns PredictiveModelingService().get_rep_forecast(db, rep_id=rep_id)
  GET /api/v1/managers/{manager_id}/team-forecast
    - Auth: manager only
    - Returns PredictiveModelingService().get_team_forecast(db, manager_id=manager_id, org_id=current_user.org_id)

Write tests in backend/tests/test_predictive_modeling.py:
  - test_forecast_computed_and_persisted: Build skill profile with 5 sessions of known scores,
    call compute_and_persist_forecast, assert RepSkillForecast rows exist with correct velocity
  - test_sessions_to_readiness_formula: Skill at 5.0, velocity 0.5/session → sessions_to_readiness = ceil((7.0-5.0)/0.5) = 4
  - test_zero_velocity_returns_none: velocity <= 0 → sessions_to_readiness = None
  - test_team_forecast_aggregation: 3 reps with varying velocities, assert reps_at_risk count correct
```

---

## Phase PM2 — At-Risk Detection & Plateau Identification

### Goal
Identify reps who are plateauing, declining, or disengaging — before the manager notices manually. Store a risk score in the database. Trigger manager-facing alerts when a rep crosses a risk threshold.

### New Model: `RepRiskScore`

```python
class RepRiskScore(Base, TimestampMixin):
    __tablename__ = "rep_risk_scores"
    __table_args__ = (
        UniqueConstraint("rep_id", name="uq_rep_risk_score_rep"),
        Index("ix_rep_risk_scores_org_risk", "org_id", "risk_level"),
        Index("ix_rep_risk_scores_manager", "manager_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0.0–1.0
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")  # low/medium/high/critical
    is_plateauing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_declining: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_disengaging: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    plateau_duration_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decline_slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_since_last_session: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_frequency_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_frequency_30d: Mapped[float | None] = mapped_column(Float, nullable=True)

    triggered_alerts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)  # ["plateau", "decline", "disengaging"]
    alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    suppressed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # snooze
```

### Risk Scoring Algorithm

```
plateau_score (0–0.4):
  - Rolling window of last 8 sessions: if score std_dev < 0.3 and sessions >= 5 → is_plateauing = True
  - score_contribution = 0.4 if is_plateauing else 0.0

decline_score (0–0.4):
  - Linear regression over last 10 sessions (or all if < 10)
  - If slope < -0.05 per session → is_declining = True
  - score_contribution = min(0.4, abs(slope) * 4)

disengagement_score (0–0.2):
  - days_since_last_session from DimRep.last_session_at
  - If days_since_last_session > 7: is_disengaging = True
  - score_contribution = min(0.2, (days_since_last_session - 7) / 14 * 0.2)

risk_score = plateau_score + decline_score + disengagement_score
risk_level:
  - < 0.2 → "low"
  - 0.2–0.4 → "medium"
  - 0.4–0.7 → "high"
  - >= 0.7 → "critical"
```

### Service Methods (add to `PredictiveModelingService`)

```python
def compute_and_persist_risk_score(
    self, db: Session, *, rep_id: str, org_id: str, manager_id: str,
    score_history: list[float], last_session_at: datetime | None
) -> dict:
    """Computes risk score, upserts RepRiskScore, returns risk dict."""

def get_at_risk_reps(
    self, db: Session, *, manager_id: str, org_id: str,
    min_risk_level: str = "medium"
) -> list[dict]:
    """Returns all reps at or above min_risk_level for a manager, ordered by risk_score desc."""

def snooze_risk_alert(
    self, db: Session, *, rep_id: str, snooze_days: int = 7
) -> None:
    """Sets suppressed_until on RepRiskScore to prevent repeated alerts."""
```

### Integration Points
- `PredictiveModelingService.compute_and_persist_forecast()` also calls `compute_and_persist_risk_score()` so both are updated together whenever a plan is built.
- `ManagerAiCoachingService.generate_rep_insight()` includes `risk_level` and `triggered_alerts` in the rep insight response.
- `generate_weekly_team_briefing()` uses `get_at_risk_reps()` to populate `needs_attention` field.

### New API Endpoints
```
GET  /api/v1/managers/{manager_id}/at-risk-reps               → list of reps at risk
POST /api/v1/reps/{rep_id}/snooze-risk-alert                   → snooze for N days
GET  /api/v1/reps/{rep_id}/risk-score                         → single rep risk detail
```

### Alembic Migration
`20260308_0023_rep_risk_scores.py`

---

### Codex Prompt — PM2

```
Implement Phase PM2 of the Predictive Modeling layer for DoorDrill.

**Add to backend/app/models/predictive.py:**
New model RepRiskScore:
- Table: rep_risk_scores
- Columns: id (String PK), rep_id (FK users CASCADE), org_id (FK organizations CASCADE),
  manager_id (FK users CASCADE), risk_score (Float default 0.0), risk_level (String 16 default "low"),
  is_plateauing (Boolean default False), is_declining (Boolean default False),
  is_disengaging (Boolean default False), plateau_duration_sessions (Integer nullable),
  decline_slope (Float nullable), days_since_last_session (Integer nullable),
  session_frequency_7d (Float nullable), session_frequency_30d (Float nullable),
  triggered_alerts (JSON default []), alert_sent_at (DateTime tz nullable),
  risk_computed_at (DateTime tz), suppressed_until (DateTime tz nullable)
- Unique constraint on rep_id
- Indexes: ix_rep_risk_scores_org_risk on (org_id, risk_level), ix_rep_risk_scores_manager on manager_id

**Add to backend/app/services/predictive_modeling_service.py:**

Method compute_and_persist_risk_score(db, *, rep_id, org_id, manager_id, score_history: list[float], last_session_at: datetime | None) -> dict:

Plateau detection:
  - Take last 8 scores (or all if fewer). If len >= 5 and std_dev(scores) < 0.3 → is_plateauing = True
  - plateau_score = 0.4 if is_plateauing else 0.0
  - plateau_duration_sessions = len of the plateau window

Decline detection:
  - Take last 10 scores (or all). Run numpy.polyfit(range(len), scores, 1) to get slope.
  - If slope < -0.05 → is_declining = True
  - decline_score = min(0.4, abs(slope) * 4)

Disengagement detection:
  - days_since = (now - last_session_at).days if last_session_at else None
  - If days_since is None or days_since > 7 → is_disengaging = True
  - disengagement_score = min(0.2, max(0, (days_since - 7) / 14 * 0.2)) if days_since else 0.2

risk_score = plateau_score + decline_score + disengagement_score (capped at 1.0)
risk_level: < 0.2 → "low", 0.2–0.4 → "medium", 0.4–0.7 → "high", >= 0.7 → "critical"
triggered_alerts = list of: "plateau" if is_plateauing, "decline" if is_declining, "disengaging" if is_disengaging

Upsert RepRiskScore (INSERT ... ON CONFLICT DO UPDATE). Check suppressed_until — if set and in the future, skip alert_sent_at update.
Return dict: {rep_id, risk_score, risk_level, is_plateauing, is_declining, is_disengaging, triggered_alerts, decline_slope, days_since_last_session}

Method get_at_risk_reps(db, *, manager_id, org_id, min_risk_level="medium") -> list[dict]:
  - RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
  - Query RepRiskScore where manager_id=manager_id, org_id=org_id, risk_level >= min_risk_level (by RISK_ORDER)
  - Filter out rows where suppressed_until is not None and suppressed_until > now()
  - Order by risk_score desc. Return list of risk dicts.

Method snooze_risk_alert(db, *, rep_id, snooze_days=7) -> None:
  - Update RepRiskScore.suppressed_until = now + timedelta(days=snooze_days) for rep_id.

**Modify compute_and_persist_forecast() to also call compute_and_persist_risk_score() using the flattened score_history from skill_profile[0]["history"] as a proxy for overall trajectory.**

**Modify ManagerAiCoachingService.generate_rep_insight():**
- After building the plan snapshot, query RepRiskScore for the rep
- If found, append risk_level and triggered_alerts to the rep_insight response dict and inject them into the LLM prompt context: "Risk flags: {triggered_alerts}. The manager should be aware of these signals."

**Modify ManagerAiCoachingService.generate_weekly_team_briefing():**
- Replace the current hardcoded needs_attention logic with get_at_risk_reps() result
- Use the top at-risk rep (highest risk_score) as the needs_attention entry

**New Alembic migration: backend/alembic/versions/20260308_0023_rep_risk_scores.py**

**New API endpoints (add to existing manager router or new predictive router):**
  GET /api/v1/managers/{manager_id}/at-risk-reps?min_risk_level=medium
  GET /api/v1/reps/{rep_id}/risk-score
  POST /api/v1/reps/{rep_id}/snooze-risk-alert  body: {"snooze_days": 7}

**Tests in backend/tests/test_predictive_modeling.py (add to existing file):**
  - test_plateau_detection: 8 sessions all scoring 5.0 → is_plateauing=True, risk_score >= 0.4
  - test_decline_detection: scores [7,6.5,6,5.5,5,4.5,4,3.5,3,2.5] → is_declining=True
  - test_disengagement_30_days: last_session_at = 30 days ago → is_disengaging=True
  - test_risk_level_thresholds: risk_score=0.1→"low", 0.3→"medium", 0.55→"high", 0.75→"critical"
  - test_snooze_suppresses_at_risk_query: snooze a rep, assert get_at_risk_reps excludes them
```

---

## Phase PM3 — Outcome-Driven Scenario Recommendation

### Goal
Upgrade `AdaptiveTrainingService` scenario recommendations from pure skill-profile matching to outcome-driven selection. Use historical `AdaptiveRecommendationOutcome` data to answer: "For reps whose weakest skill was `objection_handling` at difficulty 2, which scenario type produced the highest average skill_delta?"

This is collaborative filtering at the scenario level — no external ML needed, just SQL aggregation over `adaptive_recommendation_outcomes`.

### New Model: `ScenarioOutcomeAggregate`

```python
class ScenarioOutcomeAggregate(Base, TimestampMixin):
    __tablename__ = "scenario_outcome_aggregates"
    __table_args__ = (
        UniqueConstraint("scenario_id", "focus_skill", "difficulty_bucket", name="uq_scenario_outcome_agg"),
        Index("ix_scenario_outcome_agg_skill_difficulty", "focus_skill", "difficulty_bucket"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    focus_skill: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty_bucket: Mapped[int] = mapped_column(Integer, nullable=False)   # 1/2/3
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_skill_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_outcome_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

### Service Methods (add to `PredictiveModelingService`)

```python
def refresh_scenario_outcome_aggregates(self, db: Session, *, org_id: str | None = None) -> int:
    """
    Nightly job: aggregates AdaptiveRecommendationOutcome records by
    (scenario_id, focus_skill, difficulty_bucket). Upserts ScenarioOutcomeAggregate.
    Returns count of rows upserted.
    Can be scoped to an org or run globally.
    """

def get_outcome_ranked_scenarios(
    self, db: Session, *, focus_skill: str, difficulty: int, limit: int = 5
) -> list[dict]:
    """
    Returns top scenarios for a given (focus_skill, difficulty) sorted by avg_skill_delta desc.
    Falls back to empty list if sample_size < 3 (not enough evidence).
    """
```

### Integration with `AdaptiveTrainingService`

Modify `_recommend_scenarios()` to call `get_outcome_ranked_scenarios()` and boost the score of scenarios that appear in the outcome-ranked list:

```python
# In _recommend_scenarios:
outcome_ranked = predictive_service.get_outcome_ranked_scenarios(
    db, focus_skill=weakest_skills[0], difficulty=recommended_difficulty
)
outcome_scenario_ids = {r["scenario_id"] for r in outcome_ranked}

for rec in recommendations:
    if rec["scenario_id"] in outcome_scenario_ids:
        rec["outcome_boost"] = True
        rec["avg_skill_delta_historical"] = next(
            r["avg_skill_delta"] for r in outcome_ranked
            if r["scenario_id"] == rec["scenario_id"]
        )
```

### Nightly Refresh
Add `refresh_scenario_outcome_aggregates` to the existing `WarehouseEtlService` nightly job or create a standalone scheduled task triggered by cron or APScheduler.

### Alembic Migration
`20260308_0024_scenario_outcome_aggregates.py`

---

### Codex Prompt — PM3

```
Implement Phase PM3 of the Predictive Modeling layer for DoorDrill.

**Add to backend/app/models/predictive.py:**
New model ScenarioOutcomeAggregate:
- Table: scenario_outcome_aggregates
- Columns: id (String PK), scenario_id (FK scenarios CASCADE), focus_skill (String 64),
  difficulty_bucket (Integer), sample_size (Integer default 0), success_rate (Float nullable),
  avg_skill_delta (Float nullable), avg_outcome_score (Float nullable),
  last_refreshed_at (DateTime timezone=True)
- Unique constraint on (scenario_id, focus_skill, difficulty_bucket)
- Index on (focus_skill, difficulty_bucket)

**Add to backend/app/services/predictive_modeling_service.py:**

Method refresh_scenario_outcome_aggregates(db, *, org_id=None) -> int:
  - Query all AdaptiveRecommendationOutcome where outcome_written_at is not None
  - If org_id provided, join through Assignment to filter by org
  - Group by (recommended_scenario_id, recommended_focus_skills[0], recommended_difficulty)
    using Python defaultdict (not raw SQL GROUP BY, to stay ORM-friendly)
  - For each group compute: sample_size, success_rate = mean(recommendation_success),
    avg_skill_delta = mean of skill_delta[focus_skill] values (skip None),
    avg_outcome_score = mean(outcome_overall_score)
  - Upsert ScenarioOutcomeAggregate using merge or INSERT ON CONFLICT
  - Return count of rows written

Method get_outcome_ranked_scenarios(db, *, focus_skill, difficulty, limit=5) -> list[dict]:
  - Query ScenarioOutcomeAggregate where focus_skill=focus_skill, difficulty_bucket=difficulty,
    sample_size >= 3
  - Order by avg_skill_delta desc nulls last
  - Return list of dicts: {scenario_id, focus_skill, difficulty_bucket, sample_size, success_rate, avg_skill_delta}
  - Return [] if no qualifying rows

**Modify backend/app/services/adaptive_training_service.py:**
In _recommend_scenarios() (or just after it returns in build_plan()):
  - Instantiate PredictiveModelingService
  - Call get_outcome_ranked_scenarios(db, focus_skill=weakest_skills[0], difficulty=recommended_difficulty)
  - For each recommendation in the returned list, find matching scenario by scenario_id.
    If match found, add "outcome_boost": True and "avg_skill_delta_historical": <value> to the recommendation dict.
  - Sort recommendations: outcome_boosted ones first, then by existing score.

**Modify backend/app/services/warehouse_etl_service.py:**
At the end of the nightly ETL run method, add a call to:
  PredictiveModelingService().refresh_scenario_outcome_aggregates(db)

**New Alembic migration: backend/alembic/versions/20260308_0024_scenario_outcome_aggregates.py**

**Tests in backend/tests/test_predictive_modeling.py:**
  - test_outcome_aggregate_refresh: Create 5 AdaptiveRecommendationOutcome rows for the same
    (scenario, skill, difficulty), call refresh_scenario_outcome_aggregates, assert 1 row written
    with correct success_rate and avg_skill_delta
  - test_outcome_ranked_returns_sorted: Create aggregates with different avg_skill_deltas,
    assert get_outcome_ranked_scenarios returns them in desc order
  - test_sample_size_filter: Aggregate with sample_size=2 should not appear in results
  - test_outcome_boost_applied_to_recommendations: Create scenario + outcomes, call build_plan,
    assert top recommendation has outcome_boost=True
```

---

## Phase PM4 — Cohort Benchmarking & Percentile Ranking

### Goal
Answer the question: "Compared to other reps hired around the same time, how is this rep performing?" Give reps and managers a percentile rank per skill vs. their hire cohort and vs. the full org.

Uses `DimRep.hire_cohort` (a `Date` column) for cohort grouping. Cohorts are bucketed by quarter (e.g. "2025-Q1"). Percentile ranks are recomputed nightly by the warehouse ETL.

### New Model: `RepCohortBenchmark`

```python
class RepCohortBenchmark(Base, TimestampMixin):
    __tablename__ = "rep_cohort_benchmarks"
    __table_args__ = (
        UniqueConstraint("rep_id", "skill", name="uq_rep_cohort_benchmark_rep_skill"),
        Index("ix_rep_cohort_benchmarks_rep", "rep_id"),
        Index("ix_rep_cohort_benchmarks_org_cohort", "org_id", "cohort_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    skill: Mapped[str] = mapped_column(String(64), nullable=False)  # or "overall"
    cohort_label: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "2025-Q1"
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_p25: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_p50: Mapped[float | None] = mapped_column(Float, nullable=True)
    cohort_p75: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_in_cohort: Mapped[float | None] = mapped_column(Float, nullable=True)   # 0–100
    percentile_in_org: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

### Service Methods (add to `PredictiveModelingService`)

```python
def refresh_cohort_benchmarks(self, db: Session, *, org_id: str) -> int:
    """
    For each skill + "overall", compute cohort stats for all active reps in org.
    Cohort = same hire_cohort quarter (DimRep.hire_cohort truncated to quarter).
    Uses scipy.stats.percentileofscore for percentile calculation.
    Returns count of rows written.
    """

def get_rep_benchmarks(self, db: Session, *, rep_id: str) -> dict:
    """
    Returns all RepCohortBenchmark rows for a rep, formatted as:
    {
      rep_id, cohort_label, cohort_size,
      skills: [{
        skill, current_score, cohort_mean, cohort_p50,
        percentile_in_cohort, percentile_in_org,
        interpretation: "Above average" | "Average" | "Below average" | "Top performer"
      }]
    }
    """
```

### Interpretation Labels

```
percentile_in_cohort >= 80 → "Top performer"
percentile_in_cohort >= 55 → "Above average"
percentile_in_cohort >= 35 → "Average"
percentile_in_cohort < 35  → "Below average"
```

### Integration Points
- Add `benchmark_summary` to `generate_rep_insight()` prompt context: "Rep is in the Xth percentile for objection_handling among their hire cohort."
- Add `get_rep_benchmarks()` response to `/api/v1/reps/{rep_id}/forecast` endpoint (PM1 endpoint is extended, not duplicated).
- `refresh_cohort_benchmarks()` is called in nightly warehouse ETL per org.

### Alembic Migration
`20260308_0025_rep_cohort_benchmarks.py`

---

### Codex Prompt — PM4

```
Implement Phase PM4 of the Predictive Modeling layer for DoorDrill.

**Add to backend/app/models/predictive.py:**
New model RepCohortBenchmark:
- Table: rep_cohort_benchmarks
- Columns: id (String PK), rep_id (FK users CASCADE), org_id (FK organizations CASCADE),
  skill (String 64), cohort_label (String 16), cohort_size (Integer default 0),
  current_score (Float nullable), cohort_mean (Float nullable), cohort_p25 (Float nullable),
  cohort_p50 (Float nullable), cohort_p75 (Float nullable),
  percentile_in_cohort (Float nullable), percentile_in_org (Float nullable),
  benchmark_computed_at (DateTime timezone=True)
- Unique constraint on (rep_id, skill)
- Index on rep_id, index on (org_id, cohort_label)

**Add to backend/app/services/predictive_modeling_service.py:**

Helper _quarter_label(hire_date: date) -> str:
  - Returns e.g. "2025-Q1" from a date. Quarter = ceil(month/3).

Method refresh_cohort_benchmarks(db, *, org_id) -> int:
  - Query all DimRep where org_id=org_id, is_active=True, hire_cohort is not None
  - Group reps by _quarter_label(hire_cohort)
  - For each cohort group, for each skill in ["overall", "opening", "rapport", "pitch_clarity",
    "objection_handling", "closing"]:
      - For each rep in cohort, get their current score from RepSkillForecast.current_score
        (or FactRepDaily latest avg_score for "overall")
      - scores = [score for all reps in cohort if score is not None]
      - cohort_mean = mean(scores), cohort_p25/p50/p75 = np.percentile(scores, [25,50,75])
      - For each rep: percentile_in_cohort = scipy.stats.percentileofscore(scores, rep_score)
      - Also compute percentile_in_org across ALL reps in org (not just cohort)
      - Upsert RepCohortBenchmark rows
  - Return count written

Method get_rep_benchmarks(db, *, rep_id) -> dict:
  - Query all RepCohortBenchmark for rep_id
  - For each row compute interpretation:
    >= 80 → "Top performer", >= 55 → "Above average", >= 35 → "Average", < 35 → "Below average"
  - Return structured dict with cohort_label, cohort_size, and list of skill dicts

**Modify generate_rep_insight() in ManagerAiCoachingService:**
  - After building plan snapshot, call get_rep_benchmarks(db, rep_id=rep_id)
  - Inject into prompt: "Cohort benchmarks: {summary of percentile_in_cohort per skill}"

**Modify /api/v1/reps/{rep_id}/forecast endpoint (from PM1):**
  - Also call get_rep_benchmarks(db, rep_id=rep_id) and include "cohort_benchmarks" in the response

**Modify warehouse_etl_service.py nightly job:**
  - After refresh_scenario_outcome_aggregates, call refresh_cohort_benchmarks(db, org_id=org.id)
    for each org

**New Alembic migration: backend/alembic/versions/20260308_0025_rep_cohort_benchmarks.py**

**Tests:**
  - test_quarter_label: date(2025, 2, 15) → "2025-Q1", date(2025, 7, 1) → "2025-Q3"
  - test_cohort_benchmarks_refresh: 4 reps with known scores in same cohort, assert p50 correct
  - test_percentile_calculation: rep at median score → percentile_in_cohort ≈ 50
  - test_interpretation_labels: 85th percentile → "Top performer", 40th → "Average"
  - test_get_rep_benchmarks_returns_all_skills: 6 RepCohortBenchmark rows → dict has 6 skill entries
```

---

## Phase PM5 — Manager Coaching Impact Scoring

### Goal
Measure whether manager interventions (coaching notes, override labels) actually improve rep performance in subsequent sessions. Answer: "Did that coaching note work?" Give managers a feedback loop on their own effectiveness.

### New Model: `ManagerCoachingImpact`

```python
class ManagerCoachingImpact(Base, TimestampMixin):
    __tablename__ = "manager_coaching_impacts"
    __table_args__ = (
        Index("ix_manager_coaching_impact_manager", "manager_id"),
        Index("ix_manager_coaching_impact_rep", "rep_id"),
        Index("ix_manager_coaching_impact_session", "source_session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rep_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    source_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)

    intervention_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "coaching_note" | "override_label"
    intervention_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pre_intervention_score: Mapped[float | None] = mapped_column(Float, nullable=True)   # avg of last 3 before
    post_intervention_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # avg of next 3 after
    score_delta: Mapped[float | None] = mapped_column(Float, nullable=True)              # post - pre
    sessions_observed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observation_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    impact_classified: Mapped[str | None] = mapped_column(String(16), nullable=True)    # "positive"/"neutral"/"negative"
    impact_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### Service Methods (add to `PredictiveModelingService`)

```python
def compute_coaching_impact(
    self, db: Session, *, manager_id: str, org_id: str,
    lookback_days: int = 60
) -> int:
    """
    For all coaching notes and override labels created in the last lookback_days:
    - Find sessions within 14 days after each intervention for that rep
    - Compute pre/post score delta
    - Upsert ManagerCoachingImpact rows
    Returns count processed.
    """

def get_manager_impact_summary(
    self, db: Session, *, manager_id: str
) -> dict:
    """
    {
      manager_id,
      total_interventions_measured: int,
      avg_score_delta: float,          # mean post-pre across all interventions
      positive_impact_rate: float,     # % of interventions where score_delta > 0.3
      best_impact_rep: {rep_id, name, avg_delta},
      coaching_note_avg_delta: float,
      override_label_avg_delta: float,
      recent_impacts: [last 5]
    }
    """
```

### Impact Classification

```
score_delta > 0.5 → "positive"
score_delta > -0.3 → "neutral"
score_delta <= -0.3 → "negative"
```

### Integration Points
- `generate_weekly_team_briefing()` includes `manager_coaching_effectiveness: {avg_score_delta, positive_impact_rate}` in the briefing payload.
- New endpoint: `GET /api/v1/managers/{manager_id}/coaching-impact`
- Called nightly in warehouse ETL for all managers.

### Alembic Migration
`20260308_0026_manager_coaching_impacts.py`

---

### Codex Prompt — PM5

```
Implement Phase PM5 of the Predictive Modeling layer for DoorDrill.

**Add to backend/app/models/predictive.py:**
New model ManagerCoachingImpact:
- Table: manager_coaching_impacts
- Columns: id (String PK), manager_id (FK users CASCADE), rep_id (FK users CASCADE),
  org_id (FK organizations CASCADE), source_session_id (FK sessions CASCADE),
  intervention_type (String 32), intervention_at (DateTime tz),
  pre_intervention_score (Float nullable), post_intervention_score (Float nullable),
  score_delta (Float nullable), sessions_observed (Integer default 0),
  observation_window_days (Integer default 14), impact_classified (String 16 nullable),
  impact_computed_at (DateTime tz nullable)
- Indexes on manager_id, rep_id, source_session_id

**Add to backend/app/services/predictive_modeling_service.py:**

Method compute_coaching_impact(db, *, manager_id, org_id, lookback_days=60) -> int:
  - Query ManagerReview (coaching notes) and OverrideLabel created in last lookback_days for manager_id
  - For each intervention, get the session's overall_score as pre_intervention_score proxy
  - Query FactSession for same rep_id, session_date within 14 days after intervention_at
  - pre_score = avg of the 3 sessions immediately BEFORE intervention (from FactSession)
  - post_score = avg of the 3 sessions immediately AFTER intervention (from FactSession)
  - score_delta = post_score - pre_score
  - impact_classified: > 0.5 → "positive", > -0.3 → "neutral", <= -0.3 → "negative"
  - Upsert ManagerCoachingImpact. Return count.

Method get_manager_impact_summary(db, *, manager_id) -> dict:
  - Query all ManagerCoachingImpact for manager_id where impact_computed_at is not None
  - Compute: total_interventions_measured, avg_score_delta, positive_impact_rate,
    coaching_note_avg_delta (filter intervention_type="coaching_note"),
    override_label_avg_delta (filter intervention_type="override_label")
  - best_impact_rep: group by rep_id, find rep with highest avg score_delta, include rep name from DimRep
  - recent_impacts: last 5 by impact_computed_at desc
  - Return dict

**Modify ManagerAiCoachingService.generate_weekly_team_briefing():**
  - Call get_manager_impact_summary(db, manager_id=manager_id)
  - Add "manager_coaching_effectiveness": {avg_score_delta, positive_impact_rate} to briefing payload
  - Inject into LLM prompt: "Your recent coaching interventions show {avg_score_delta:+.2f} avg score delta
    with {positive_impact_rate:.0%} positive impact rate."

**New Alembic migration: backend/alembic/versions/20260308_0026_manager_coaching_impacts.py**

**New API endpoint:**
  GET /api/v1/managers/{manager_id}/coaching-impact
    - Returns get_manager_impact_summary()

**Add compute_coaching_impact to nightly warehouse ETL for each manager.**

**Tests:**
  - test_positive_impact: pre_score=5.0, post_score=6.5 → score_delta=1.5, impact_classified="positive"
  - test_neutral_impact: pre_score=6.0, post_score=6.2 → "neutral"
  - test_negative_impact: pre_score=7.0, post_score=6.0 → "negative"
  - test_manager_impact_summary: 10 interventions, 7 positive → positive_impact_rate=0.7
  - test_no_post_sessions: intervention with no subsequent sessions → score_delta=None, not upserted
```

---

## Phase PM6 — Team Performance Forecasting Dashboard Data

### Goal
Aggregate all PM1–PM5 signals into a single "team intelligence snapshot" endpoint that powers the manager's predictive dashboard view. This is a read-only aggregation layer — no new models, no new DB writes. It composes existing service methods into one optimized response suitable for the frontend.

### New Service Method

```python
# In PredictiveModelingService

def get_team_intelligence_snapshot(
    self, db: Session, *, manager_id: str, org_id: str
) -> dict:
    """
    Combines team forecast (PM1) + at-risk reps (PM2) + coaching impact (PM5)
    into a single dashboard payload.

    Returns:
    {
      manager_id, org_id, snapshot_at,

      # Team readiness overview
      team_size: int,
      avg_readiness_score: float,
      reps_ready: int,
      reps_on_track: int,
      reps_at_risk: int,
      projected_team_readiness_in_sessions: int,   # median sessions_to_readiness across team

      # Skill breakdown
      team_skill_averages: {skill: avg_score},
      weakest_team_skill: str,
      strongest_team_skill: str,

      # At-risk detail
      at_risk_reps: [{ rep_id, name, risk_level, triggered_alerts, days_since_last_session }],

      # Cohort context
      cohort_comparison: {
        reps_above_cohort_median: int,
        reps_below_cohort_median: int,
      },

      # Manager effectiveness
      coaching_effectiveness: {
        avg_score_delta: float,
        positive_impact_rate: float,
      },

      # 30/60/90 day projection
      projection: {
        "30d": { projected_avg_score: float, reps_reaching_readiness: int },
        "60d": { projected_avg_score: float, reps_reaching_readiness: int },
        "90d": { projected_avg_score: float, reps_reaching_readiness: int },
      }
    }
    """
```

### 30/60/90 Projection Logic

```
For each rep:
  - Load RepSkillForecast (velocity per skill)
  - sessions_per_day = session_frequency_7d from RepRiskScore (or assume 0.5 sessions/day)
  - sessions_in_30d = sessions_per_day * 30
  - projected_score_30d = current_score + (velocity * sessions_in_30d)
  - rep reaches readiness if projected_score_30d >= READINESS_THRESHOLD
Aggregate across team.
```

### New API Endpoint
```
GET /api/v1/managers/{manager_id}/team-intelligence
```

### Codex Prompt — PM6

```
Implement Phase PM6 of the Predictive Modeling layer for DoorDrill.

**Add to backend/app/services/predictive_modeling_service.py:**

Method get_team_intelligence_snapshot(db, *, manager_id, org_id) -> dict:
  - Call get_team_forecast(db, manager_id=manager_id, org_id=org_id) for readiness overview
  - Call get_at_risk_reps(db, manager_id=manager_id, org_id=org_id, min_risk_level="medium")
  - Call get_manager_impact_summary(db, manager_id=manager_id)
  - Query RepSkillForecast for all reps under manager → compute team_skill_averages (mean per skill)
  - Compute weakest_team_skill = skill with lowest avg, strongest_team_skill = highest avg

  30/60/90 projection:
  - For each rep, get RepSkillForecast (overall velocity) and RepRiskScore (session_frequency_7d)
  - sessions_per_day = session_frequency_7d / 7 if available else 0.5 (conservative default)
  - For each horizon in [30, 60, 90]:
      projected_scores = [current_score + velocity * (sessions_per_day * days) for each rep]
      reps_reaching_readiness = count where projected_score >= 7.0
      projected_avg_score = mean(projected_scores)
  - If velocity is None for a rep, use current_score (assume plateau)

  Cohort comparison:
  - Query RepCohortBenchmark for all reps, skill="overall"
  - Count reps where percentile_in_cohort >= 50 → reps_above_cohort_median
  - Count reps where percentile_in_cohort < 50 → reps_below_cohort_median

  Assemble and return the full snapshot dict with snapshot_at = datetime.now(UTC)

**New API endpoint:**
  GET /api/v1/managers/{manager_id}/team-intelligence
    - Auth: manager only (verify current_user.id == manager_id or is_admin)
    - Returns PredictiveModelingService().get_team_intelligence_snapshot(...)

**Tests:**
  - test_team_intelligence_snapshot_structure: Assert all top-level keys present in response
  - test_30_60_90_projection_increases: reps with positive velocity → reps_reaching_readiness
    increases from 30d to 90d projection
  - test_projection_with_no_velocity: rep with velocity=None → uses current_score (no crash)
  - test_team_intelligence_empty_team: manager with no reps → returns zeros, no crash
  - test_weakest_skill_identification: team where "objection_handling" has lowest avg → weakest_team_skill="objection_handling"
```

---

## Phase Sequence & Dependencies

```
PM1 (forecasts)
  └─ PM2 (risk scores) ← depends on PM1's score_history
      └─ PM3 (scenario aggregates) ← depends on AdaptiveRecommendationOutcome
          └─ PM4 (cohort benchmarks) ← depends on PM1 forecasts for current_score
              └─ PM5 (coaching impact) ← depends on FactSession + ManagerReview
                  └─ PM6 (team intelligence) ← composes PM1+PM2+PM4+PM5
```

Run Codex phases strictly in this order. Each phase must pass its tests before proceeding.

---

## Alembic Migration Sequence

| Migration | Table | Depends On |
|---|---|---|
| `0022_predictive_skill_forecasts` | `rep_skill_forecasts` | `users`, `organizations` |
| `0023_rep_risk_scores` | `rep_risk_scores` | `users`, `organizations` |
| `0024_scenario_outcome_aggregates` | `scenario_outcome_aggregates` | `scenarios` |
| `0025_rep_cohort_benchmarks` | `rep_cohort_benchmarks` | `users`, `organizations` |
| `0026_manager_coaching_impacts` | `manager_coaching_impacts` | `users`, `organizations`, `sessions` |

No new pgvector columns — all predictive models use standard Float/JSON types.

---

## One-Liner Codex Execution Reference

```bash
# PM1
"Implement Phase PM1 of PRD_PREDICTIVE_MODELING.md — Skill Velocity & Readiness Forecasting. New model RepSkillForecast in models/predictive.py, new PredictiveModelingService with compute_and_persist_forecast() and linear regression, integrate into AdaptiveTrainingService.build_plan(), new /reps/{rep_id}/forecast and /managers/{manager_id}/team-forecast endpoints, migration 0022, tests for velocity/sessions_to_readiness/zero_velocity cases."

# PM2
"Implement Phase PM2 of PRD_PREDICTIVE_MODELING.md — At-Risk Detection. New model RepRiskScore in models/predictive.py, add compute_and_persist_risk_score()/get_at_risk_reps()/snooze_risk_alert() to PredictiveModelingService, integrate into generate_rep_insight() and generate_weekly_team_briefing(), migration 0023, tests for plateau/decline/disengagement/snooze."

# PM3
"Implement Phase PM3 of PRD_PREDICTIVE_MODELING.md — Outcome-Driven Scenario Recommendation. New model ScenarioOutcomeAggregate, add refresh_scenario_outcome_aggregates()/get_outcome_ranked_scenarios() to PredictiveModelingService, boost outcome-proven scenarios in AdaptiveTrainingService._recommend_scenarios(), add to warehouse ETL nightly job, migration 0024, tests."

# PM4
"Implement Phase PM4 of PRD_PREDICTIVE_MODELING.md — Cohort Benchmarking. New model RepCohortBenchmark, add refresh_cohort_benchmarks()/get_rep_benchmarks() to PredictiveModelingService, inject cohort context into generate_rep_insight(), extend /forecast endpoint with cohort_benchmarks, migration 0025, tests."

# PM5
"Implement Phase PM5 of PRD_PREDICTIVE_MODELING.md — Manager Coaching Impact. New model ManagerCoachingImpact, add compute_coaching_impact()/get_manager_impact_summary() to PredictiveModelingService, inject into weekly briefing, new /managers/{id}/coaching-impact endpoint, migration 0026, tests."

# PM6
"Implement Phase PM6 of PRD_PREDICTIVE_MODELING.md — Team Intelligence Snapshot. Add get_team_intelligence_snapshot() to PredictiveModelingService composing PM1+PM2+PM4+PM5 signals, 30/60/90 day projections using velocity × session_frequency, new /managers/{id}/team-intelligence endpoint, tests."
```

---

## Non-Goals (Out of Scope for PM1–PM6)

- External CRM integration for real-world sales outcome correlation (requires separate PRD)
- Deep learning / neural network models (out of scope until dataset exceeds ~50k sessions)
- Real-time streaming predictions (current batch-on-plan-build pattern is sufficient)
- A/B testing predictive model variants (handled by existing PromptExperiment framework)
