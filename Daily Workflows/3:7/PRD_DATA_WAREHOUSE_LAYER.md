# PRD: Data Warehouse Layer
## Star Schema, Materialized Views, and Fast Analytics at Scale

**Owner:** Engineering
**Status:** Ready for implementation
**Depends on:** Transcript Pipeline (structured turn records) improves warehouse quality — but warehouse can ship independently
**Feeds into:** Manager Dashboard animated heatmaps, risk intelligence, all aggregate queries

---

## Problem Statement

The manager dashboard computes analytics live from raw OLTP tables (`sessions`, `scorecards`, `session_turns`, `assignments`). At 10 reps, this is fine. At 100 reps drilling twice a day, every dashboard load issues 8–12 complex JOINs across tables that are also being written to by active sessions.

We have partial infrastructure: `AnalyticsMaterializedView`, `AnalyticsMetricSnapshot`, `AnalyticsPartitionWindow`, and `AnalyticsRefreshRun` models exist. But the actual star schema — `fact_sessions`, `dim_reps`, `dim_scenarios`, `dim_time` — doesn't exist. The `management_analytics_runtime_service.py` still reads directly from OLTP tables. There is no ETL pipeline that writes into the analytics layer post-session, and the materialized view rows store raw JSON blobs rather than typed, query-optimized columns.

The animated heatmaps, risk quadrant scatter plots, and rep trajectory charts in the manager dashboard need pre-aggregated data or they will degrade under real load.

---

## Goals

1. Build a proper star schema with fact and dimension tables that survive 100k sessions.
2. Wire post-session ETL so every completed session writes into the warehouse within 60 seconds.
3. Replace the ad-hoc live queries in `management_analytics_runtime_service.py` with warehouse reads for all aggregate endpoints.
4. Keep the OLTP tables (sessions, scorecards, etc.) untouched — the warehouse is a read layer, not a replacement.
5. Make the refresh pipeline idempotent so re-processing a session twice produces the same result.

---

## Non-Goals

- This PRD does NOT use an external warehouse (Snowflake, BigQuery, Redshift). Everything stays in PostgreSQL.
- This PRD does NOT replace the existing `AnalyticsMetricSnapshot` system — it extends it with a proper star schema underneath.
- This PRD does NOT implement cross-org or global aggregations. Scope is always org-scoped or manager-scoped.

---

## Star Schema Design

### Dimension Tables

#### `dim_reps`
```sql
rep_id          UUID  PK  (FK users.id)
org_id          UUID
team_id         UUID | NULL
rep_name        VARCHAR(255)
hire_cohort     DATE         -- month of first session (for cohort analysis)
industry        VARCHAR(120)
is_active       BOOLEAN
first_session_at TIMESTAMPTZ
last_session_at  TIMESTAMPTZ
total_sessions   INT          -- denormalized, refreshed with each session write
last_refreshed_at TIMESTAMPTZ
```

#### `dim_scenarios`
```sql
scenario_id     UUID  PK  (FK scenarios.id)
org_id          UUID
scenario_name   VARCHAR(255)
industry        VARCHAR(120)
difficulty      INT           -- 1–5
objection_focus JSONB         -- top objection types this scenario targets
created_by_id   UUID
is_active       BOOLEAN
last_refreshed_at TIMESTAMPTZ
```

#### `dim_time`
```sql
date_key        DATE  PK
day_of_week     SMALLINT      -- 0=Sun, 6=Sat
week_number     SMALLINT
month           SMALLINT
quarter         SMALLINT
year            SMALLINT
is_weekday      BOOLEAN
```
Pre-populate 5 years (2025–2030). No FK from fact tables — join on `DATE(fact_sessions.session_date)`.

---

### Fact Tables

#### `fact_sessions` — one row per completed, graded session
```sql
fact_session_id     UUID  PK
session_id          UUID  (FK sessions.id, UNIQUE — idempotency key)
org_id              UUID  INDEX
manager_id          UUID  INDEX
rep_id              UUID  INDEX  (FK dim_reps.rep_id)
scenario_id         UUID  INDEX  (FK dim_scenarios.scenario_id)
session_date        DATE  INDEX  (FK dim_time.date_key)
started_at          TIMESTAMPTZ
ended_at            TIMESTAMPTZ | NULL
duration_seconds    INT   | NULL
status              VARCHAR(32)

-- Grading
overall_score           FLOAT | NULL
score_opening           FLOAT | NULL
score_pitch_delivery    FLOAT | NULL
score_objection_handling FLOAT | NULL
score_closing_technique  FLOAT | NULL
score_professionalism    FLOAT | NULL
grading_confidence      FLOAT | NULL   -- from GradingRun.confidence_score
prompt_version_id       UUID  | NULL   -- from GradingRun.prompt_version_id

-- Conversation metrics
turn_count              INT
rep_turn_count          INT
ai_turn_count           INT
objection_count         INT
barge_in_count          INT
avg_rep_turn_length_chars FLOAT | NULL
final_emotion           VARCHAR(32) | NULL  -- emotion state at session end

-- Manager activity
has_manager_review      BOOLEAN  DEFAULT false
override_score          FLOAT | NULL
override_delta          FLOAT | NULL   -- abs(override_score - overall_score)
has_coaching_note       BOOLEAN  DEFAULT false

-- Weakness signals (top 3 stored flat for query efficiency)
weakness_tag_1  VARCHAR(64) | NULL
weakness_tag_2  VARCHAR(64) | NULL
weakness_tag_3  VARCHAR(64) | NULL

etl_version     VARCHAR(16)  DEFAULT '1.0'
etl_written_at  TIMESTAMPTZ
```

Indexes:
```sql
(org_id, session_date)
(manager_id, session_date)
(rep_id, session_date)
(scenario_id, session_date)
(overall_score)  -- for histogram queries
```

#### `fact_rep_daily` — one row per rep per day (pre-aggregated roll-up)
```sql
fact_rep_daily_id  UUID  PK
rep_id             UUID  INDEX
org_id             UUID  INDEX
manager_id         UUID  INDEX
session_date       DATE  INDEX
session_count      INT
scored_count       INT
avg_score          FLOAT | NULL
min_score          FLOAT | NULL
max_score          FLOAT | NULL
avg_objection_handling FLOAT | NULL
avg_closing_technique  FLOAT | NULL
total_duration_seconds INT
barge_in_count     INT
override_count     INT
coaching_note_count INT
UNIQUE(rep_id, session_date)
```

This is the primary table for the animated score trend lines and heatmaps. One JOIN replaces 3 JOINs + GROUP BY.

---

## ETL Pipeline

### Post-Session Write Path

Extend `SessionPostprocessService.run()` to include a warehouse write step after grading:

```
session ends
  → cleanup (existing)
  → grade (existing)
  → notify (existing)
  → warehouse_write  ← NEW STEP
```

```python
class WarehouseEtlService:
    """Writes a completed, graded session into the analytics star schema."""

    ETL_VERSION = "1.0"

    def write_session(self, db: Session, session_id: str) -> None:
        """
        Idempotent. Re-running for the same session_id upserts using session_id
        as the conflict key. Safe to call multiple times.
        """
        session = self._load_session_with_relations(db, session_id)
        scorecard = session.scorecard
        if scorecard is None:
            raise ValueError("session has no scorecard — grade before warehouse write")

        self._upsert_dim_rep(db, session.rep)
        self._upsert_dim_scenario(db, session.scenario)
        self._upsert_fact_session(db, session, scorecard)
        self._upsert_fact_rep_daily(db, session, scorecard)
        db.commit()

    def _upsert_fact_session(self, db, session, scorecard):
        # INSERT INTO fact_sessions ... ON CONFLICT (session_id) DO UPDATE SET ...
        ...
```

### Refresh Triggers

Three triggers write into the warehouse:

1. **Post-session** (primary): `WarehouseEtlService.write_session()` called inline in `SessionPostprocessService` after grading completes.
2. **Manager review**: When a manager submits an override, update `fact_sessions.override_score`, `override_delta`, `has_manager_review`.
3. **Coaching note**: When a coaching note is created, flip `fact_sessions.has_coaching_note`.

All three paths call the same upsert method — they're idempotent.

### Backfill

Add a management command / Celery task `backfill_warehouse` that iterates all graded sessions without a `fact_sessions` row and calls `write_session()`. Runs in batches of 200 with a 100ms sleep between batches.

---

## Replacing Live Queries in `management_analytics_runtime_service.py`

Current hot paths that scan raw tables:

| Endpoint | Current query | Warehouse replacement |
|---|---|---|
| Team skill heatmap | JOIN sessions + scorecards + users GROUP BY rep | `SELECT * FROM fact_rep_daily WHERE manager_id=? AND session_date BETWEEN ?` |
| Score trend line | SELECT sessions+scorecards per rep last 30d | `SELECT * FROM fact_sessions WHERE rep_id=? ORDER BY session_date` |
| Risk quadrant | Aggregated per-rep scores + trajectory | 2x window over `fact_rep_daily` |
| Scenario pass rates | GROUP BY scenario with pass/fail | `SELECT scenario_id, AVG(overall_score), COUNT(*) FROM fact_sessions GROUP BY scenario_id` |
| Histogram | All scores for org in period | `SELECT overall_score FROM fact_sessions WHERE org_id=? AND session_date BETWEEN ?` |

**Migration approach:** Add a `_use_warehouse: bool` flag to `ManagementAnalyticsRuntimeService`. Default `True` when `fact_sessions` rows exist for the manager's org. Fall back to live queries otherwise — ensures zero-downtime deploy before the warehouse is populated.

---

## Implementation Phases

### Phase W1: Schema + ETL skeleton
- Add `fact_sessions`, `fact_rep_daily`, `dim_reps`, `dim_scenarios`, `dim_time` models
- Alembic migration
- `WarehouseEtlService` with `write_session()` (upsert)
- Wire into `SessionPostprocessService`
- Pre-populate `dim_time` (2025–2030)
- Tests: `test_warehouse_write_session.py` (idempotency test)

### Phase W2: Dimension updates on manager actions
- Update `fact_sessions` on manager review (override_score, delta)
- Update `fact_sessions` on coaching note (has_coaching_note flag)
- Tests: `test_warehouse_update_on_review.py`

### Phase W3: Replace live queries in runtime service
- Implement warehouse-backed query methods on `ManagementAnalyticsRuntimeService`
- Add `_use_warehouse` flag with live-query fallback
- Run load test comparing p50/p95 before and after — target 40% reduction
- Tests: `test_management_analytics_runtime_track_f.py` must still pass

### Phase W4: Backfill task
- `CeleryTask: backfill_warehouse` (batch 200, idempotent)
- `GET /manager/admin/warehouse-status` (admin-only, shows backfill progress)

---

## Key Files

```
backend/app/models/warehouse.py          — NEW: fact_sessions, fact_rep_daily, dim_*
backend/app/services/warehouse_etl_service.py — NEW: WarehouseEtlService
backend/app/services/session_postprocess_service.py — MODIFY: add warehouse_write step
backend/app/services/manager_action_service.py      — MODIFY: update fact_sessions on review
backend/app/services/management_analytics_runtime_service.py — MODIFY: warehouse reads
backend/alembic/versions/                — NEW: warehouse tables migration
backend/tests/test_warehouse_etl.py     — NEW
```

---

## Success Metrics

- p50 manager dashboard load < 150ms with 500 sessions in warehouse (vs. current 600ms live query).
- `fact_sessions` row exists within 60s of session grading completing.
- Re-processing a session 3 times produces identical `fact_sessions` row (idempotency test).
- Zero regressions on `test_management_analytics_runtime_track_f.py`.
