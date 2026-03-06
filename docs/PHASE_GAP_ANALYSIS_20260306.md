# DoorDrill Management Intelligence Gap Analysis

Date: 2026-03-06
Repo audited: `/Users/calelamb/Desktop/personal projects/doordrill`

## Summary

This repo is materially ahead of the original management execution plan. The analytics foundation, command center, scenario intelligence, coaching analytics, explorer, replay-linked evidence, runtime caching, and ops scaffolding are all real code paths. The current gap is not "analytics does not exist." The gap is that some plan items are only partially implemented, some contracts do not yet match the plan, and a few foundation deliverables were implied in docs but not represented explicitly in the schema.

This document records:

1. What is implemented now.
2. What was missing before this pass.
3. What this pass adds.
4. What still remains after this pass.

## Phase Status

### Phase 1: Data Platform and DB Management

Implemented before this pass:

- Derived analytics schema in `backend/app/models/analytics.py`
- Fact tables:
  - `analytics_fact_sessions`
  - `analytics_fact_session_turn_metrics`
  - `analytics_fact_rep_day`
  - `analytics_fact_rep_week`
  - `analytics_fact_team_day`
  - `analytics_fact_scenario_day`
  - `analytics_fact_coaching_interventions`
  - `analytics_fact_manager_calibration`
- Dimensions:
  - `analytics_dim_reps`
  - `analytics_dim_managers`
  - `analytics_dim_scenarios`
- Metric registry:
  - `analytics_metric_definitions`
  - `analytics_metric_snapshots`
- Projection-backed hot reads:
  - `analytics_materialized_views`
- Refresh runs and logical partition metadata:
  - `analytics_refresh_runs`
  - `analytics_partition_windows`

Missing before this pass:

- Explicit `fact_alerts`
- Explicit `dim_teams`
- Explicit `dim_time`
- Real alert-fact persistence separate from materialized payloads

Added in this pass:

- `analytics_fact_alerts`
- `analytics_dim_teams`
- `analytics_dim_time`
- Refresh logic to rebuild persistent alert facts during manager/session refresh

Still missing after this pass:

- Physical Postgres partition DDL beyond logical partition tracking
- Polars feature jobs
- Optional ClickHouse mirror

### Phase 2: Metrics and Feature Engineering

Implemented before this pass:

- Score trend
- Category trend
- Difficulty-adjusted score
- Pass rate by scenario
- Volatility and regression risk
- Talk ratio
- Close attempts
- Retry uplift
- Coaching uplift
- Override drift
- Objection failure signals

Gaps still present:

- Broader metric registry coverage versus the full plan list
- Confidence score
- Forecast-oriented feature sets
- More explicit persisted ownership/versioning metadata per KPI

### Phase 3: Management API Layer

Implemented before this pass:

- `GET /manager/command-center`
- `GET /manager/analytics`
- `GET /manager/reps/{rep_id}/progress`
- `GET /manager/analytics/scenarios`
- `GET /manager/analytics/coaching`
- `GET /manager/analytics/explorer`
- `GET /manager/alerts`
- `GET /manager/benchmarks`
- `GET /manager/analytics/operations`
- `GET /manager/analytics/metrics/definitions`

Missing before this pass:

- `GET /manager/analytics/team`
- `GET /manager/analytics/reps/{rep_id}`
- `POST /manager/alerts/{id}/ack`

Added in this pass:

- `GET /manager/analytics/team` alias
- `GET /manager/analytics/reps/{rep_id}` alias
- `POST /manager/alerts/{id}/ack`

Still missing after this pass:

- Full shared filter contract parity for array filters, `group_by`, and cursor pagination
- Universal `empty_state_reason` payload contract

### Phase 4: Command Center

Implemented:

- Hero KPI strip
- Score trend
- Scenario pressure/pass matrix
- Rep risk matrix
- Score distribution
- Weakest categories
- Alerts preview
- Benchmark band

Still missing:

- "Why did this move?" annotation cards
- Fastest improvers panel
- Completion by rep table in the command center view itself

### Phase 5: Rep Intelligence

Implemented:

- Rep score trend
- Category radar
- Weakness tags
- Session history
- Replay drilldown

Still missing:

- Objection handling heatmap
- Scenario-by-scenario matrix
- Talk/listen and interruption trends
- Close-attempt trend
- Coaching timeline
- Improvement velocity
- Next-best-drill recommendations

### Phase 6: Scenario Intelligence

Implemented:

- Difficulty vs pass-rate scatter
- Objection failure map
- Repeat-attempt improvement delta
- Replay evidence linking

Still missing:

- Scenario volume trend
- Category breakdown by scenario
- Coaching ROI ranking
- Washout/stall ranking
- Assignment guidance by weakness tag

### Phase 7: Coaching Science

Implemented:

- Coaching uplift
- Retry impact
- Weakness-tag uplift
- Manager calibration drift
- Override bias summaries
- Intervention segments

Still missing:

- Rich attribution of note type to outcome
- Manager-to-manager consistency views
- Next-best coaching actions

### Phase 8: Session Intelligence Explorer

Implemented:

- Virtualized large session list
- Search/filtering
- Saved views
- Replay linkage

Still missing:

- CSV export
- Preview drawer
- More complete facet set
- Cursor pagination

### Phase 9: Forecasts and Alerts

Implemented before this pass:

- Rule-based alerts
- Statistical anomaly alerts

Added in this pass:

- Persisted alert facts
- Alert acknowledgement API and audit logging

Still missing:

- Readiness forecasts
- Scenario recommendation forecasts
- Predicted regression if no coaching is given

### Phase 10: Replay-Linked Evidence

Implemented:

- Transcript-linked replay
- Evidence jumps
- Focus turn routing
- Critical moments
- Barge-in markers
- Grading rationale highlights

### Phase 11: Visual System and UX

Implemented:

- Strong visual system distinct from default SaaS styling
- Mixed chart stack with ECharts-based intelligence views
- Motion and replay-driven drilldown patterns

Still missing:

- Consistent consolidation on the intended chart/table stack
- More operational interaction states around alert acknowledgement and workflow closure

### Phase 12: Performance and Ops

Implemented:

- Runtime cache
- Analytics refresh orchestration
- Load harness
- SLO gate workflow
- Freshness metadata
- Ops endpoint and runbooks

Still missing:

- Full production observability dashboards
- Cursor-based explorer reads

### Phase 13: Testing and Validation

Implemented before this pass:

- Endpoint coverage for management intelligence
- Runtime and refresh tests
- Org isolation tests
- Load/perf coverage

Added in this pass:

- Contract tests for alert acknowledgement and API aliases
- Refresh-validation tests for alert facts and new dimensions

Still missing:

- UI visual regression coverage
- Broader labeled anomaly validation

## Changes Made In This Pass

Backend foundation:

- Added explicit team/time/alert analytics tables.
- Added refresh logic to populate those tables.
- Added persistent alert-fact rebuilds during analytics refresh.

Management contracts:

- Added the missing team analytics alias endpoint.
- Added the missing rep analytics alias endpoint.
- Added alert acknowledgement endpoint with manager audit logging.

Alert lifecycle:

- Alert IDs now include evidence-specific identifiers where needed so acknowledgements suppress the current occurrence and naturally reopen when new evidence appears.
- Acknowledged alerts are filtered from active alert feeds after refresh.

## Remaining Highest-Value Next Steps

1. Finish contract parity for shared filters and cursor pagination.
2. Replace mock assignment creation with real backend wiring.
3. Build the missing rep/scenario/coaching panels that convert analytics into next actions.
4. Add first-pass readiness forecasts once enough production data exists.
