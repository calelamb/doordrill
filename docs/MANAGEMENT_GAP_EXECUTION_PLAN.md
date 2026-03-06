# DoorDrill Management Gap Closure Plan

## Objective

Close the remaining management-intelligence gaps without breaking current rep, manager, or replay workflows.

## Operating Model

- Backend work runs sequentially because schema, projections, and analytics contracts are upstream dependencies.
- Website UI work runs in parallel on stable contracts and does not touch mobile.
- Existing interfaces stay additive-only unless a migration is unavoidable.

## Track Ownership

### Track A: Data Platform

- Add stored analytics projections for hot management views.
- Add partition metadata and maintenance scaffolding for high-volume tables.
- Expand refresh/backfill jobs to populate stored projections.
- Expose projection and partition health through operations endpoints.

### Track B: Analytics Backend

- Move hot management reads onto stored projections where possible.
- Add non-trivial anomaly detection beyond static threshold alerts.
- Add stronger benchmark, trend, and drift calculations.
- Keep custom-range and drilldown queries warehouse-backed.

### Track C: Management UI

- Upgrade to a higher-density chart system.
- Add explorer virtualization and saved views.
- Improve responsive behavior for tablet and laptop widths.
- Strengthen motion and chart transitions without blocking interactions.

### Track D: Replay + Session Intelligence

- Ensure every analytics surface can deep-link to replay with turn focus.
- Add transcript evidence overlays and stronger critical-moment annotations.
- Link chart-selected categories back to replay score evidence.

### Track E: Coaching Science

- Replace simple uplift heuristics with richer intervention attribution.
- Separate coached vs uncoached retry impact more clearly.
- Add score drift and calibration interpretation suitable for manager action.
- Surface next-best coaching actions from weakness and trend signals.

### Track F: Platform Reliability

- Add management analytics observability artifacts.
- Enforce dashboard latency gates in CI and load harnesses.
- Document runbooks for stale projections, partition drift, and cache misses.
- Keep management freshness under 60 seconds.

## Sequential Delivery

1. Track A
2. Track B
3. Track F
4. Track C
5. Track D
6. Track E
7. Validation and hardening pass

## Parallel UI Agent Program

The website UI track can run in parallel after backend contracts freeze for each milestone.

### UI Milestone C1

- Introduce chart primitives and motion wrappers.
- Redesign command center layout with stronger data density.

### UI Milestone C2

- Virtualize explorer and large rep/session tables.
- Add saved analytical views and pinned filter states.

### UI Milestone C3

- Add replay-linked overlays, chart focus states, and evidence navigation.
- Tune responsive layout and transitions for tablet and desktop.

## Validation Gates

- Backend pytest stays green.
- Dashboard build stays green.
- Management analytics load harness stays within p50/p95 budgets.
- Operations endpoint shows refresh, cache, and projection health.
- Replay deep links remain functional after analytics changes.
