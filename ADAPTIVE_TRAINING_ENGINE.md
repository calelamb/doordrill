# DoorDrill Adaptive Training Engine

Repository snapshot analyzed and implemented on March 6, 2026.

## Purpose

The adaptive training engine turns DoorDrill from a static assignment system into a progression system. It evaluates graded session history, estimates a rep's current skill graph, recommends scenarios that target the weakest skills, and can create assignments with adaptive metadata embedded in the assignment policy.

Implemented files:

- `backend/app/services/adaptive_training_service.py`
- `backend/app/schemas/adaptive_training.py`
- `backend/app/api/manager.py`

Implemented endpoints:

- `GET /manager/reps/{rep_id}/adaptive-plan?manager_id=...`
- `POST /manager/reps/{rep_id}/adaptive-assignment`

## Skill Tracking Model

The current skill graph tracks five rep skills:

- `opening`
- `rapport`
- `pitch_clarity`
- `objection_handling`
- `closing`

These are derived from existing session data rather than a new table.

Primary source signals:

- `scorecards.category_scores`
  - `opening`
  - `pitch_delivery`
  - `objection_handling`
  - `closing_technique`
  - `professionalism`
- session emotion trajectory from `session_events`
- objection load from `session_turns`
- scenario difficulty from `scenarios.difficulty`

### Direct skill estimates

The service derives per-session skill estimates as follows:

- `opening`
  - mostly from scorecard opening
- `rapport`
  - opening + professionalism + emotion recovery
- `pitch_clarity`
  - pitch delivery + opening + professionalism
- `objection_handling`
  - objection score + objection load + emotion recovery + challenge bonus
- `closing`
  - closing score + pitch clarity support + emotion recovery

### Emotion recovery

The engine looks at the emotional path across the session:

- starting homeowner emotion
- ending homeowner emotion

If the rep moves the homeowner toward a more open state, that increases `emotion_recovery`, which lifts:

- rapport
- objection handling
- closing

### Recency weighting

More recent sessions count more heavily than older sessions.

This allows the skill profile to:

- reflect improvement quickly
- avoid overfitting to a rep's first few drills

## Skill Graph Model

The current graph is directed and weighted:

```text
opening -> rapport (0.35)
rapport -> pitch_clarity (0.20)
pitch_clarity -> objection_handling (0.30)
objection_handling -> closing (0.35)
rapport -> closing (0.15)
```

Interpretation:

- better openings help a rep earn rapport
- better rapport improves how clearly the pitch lands
- better pitch clarity makes objections easier to handle
- better objection handling improves close quality
- rapport also supports the close directly

The engine first computes direct skill scores, then propagates small adjustments along the graph so downstream skills reflect upstream strength or weakness without fully replacing their direct measurements.

## Example Skill Profile

Example output shape:

```text
opening: 8.1
rapport: 7.2
pitch_clarity: 6.5
objection_handling: 5.0
closing: 4.3
```

Each node also includes:

- `trend`
- `confidence`
- `contributing_metrics`

## Difficulty Adjustment Algorithm

The engine derives a recommended next difficulty from:

- current readiness score
- weakest skill score
- recent performance trend

### Inputs

- readiness score = mean of the five skill scores
- performance trend = later half of sessions minus earlier half of sessions
- weakest skill = lowest skill in the current graph

### Current logic

1. Start from readiness:
   - higher readiness lifts recommended difficulty
2. If recent trend is positive and readiness is solid:
   - increase difficulty by one step
3. If the weakest skill is still materially weak:
   - lower difficulty by one step to keep the next assignment challenging but recoverable
4. Clamp to `1-5`

### Target difficulty factors

The engine does not only recommend a scalar difficulty. It also builds a target challenge profile:

- `objection_frequency`
- `homeowner_resistance_level`
- `patience_window`
- `scenario_complexity`

Those targets are shaped by the rep's weakest skills.

Examples:

- weak `objection_handling`
  - increase objection frequency
- weak `opening` or `rapport`
  - increase homeowner resistance
  - shorten patience window
- weak `closing`
  - raise scenario complexity near the end of the drill

## Scenario Recommendation Algorithm

Every scenario is evaluated against the rep's current skill graph.

### Scenario features extracted

From each `Scenario`, the engine derives:

- objection frequency
  - based on concern count and objection stages
- homeowner resistance level
  - based on persona attitude and difficulty
- patience window
  - based on persona attitude and difficulty
- scenario complexity
  - based on difficulty, stage count, and concern count

### Scenario skill focus inference

The engine infers which skills a scenario trains most:

- door / initial pitch stages -> opening, pitch clarity
- objection stages or multiple concerns -> objection handling
- close stages -> closing
- skeptical / busy / annoyed / hostile personas -> rapport, opening
- trust / price concerns -> pitch clarity, objection handling
- spouse / timing / incumbent-provider concerns -> objection handling, closing

### Recommendation score

Each scenario gets a `recommendation_score` based on:

- weakness alignment
  - how well the scenario's skill focus matches the rep's weakest skills
- difficulty fit
  - how closely the scenario's difficulty factors match the target difficulty profile

The top-ranked scenarios are returned in `recommended_scenarios`.

Each recommendation includes:

- `scenario_id`
- `scenario_name`
- `difficulty`
- `recommendation_score`
- `focus_skills`
- `target_weaknesses`
- `difficulty_factors`
- `rationale`

## Integration with Scenario Assignment

The engine is integrated directly into assignment creation.

### Read path

`GET /manager/reps/{rep_id}/adaptive-plan`

Returns:

- session count
- readiness score
- performance trend
- recommended difficulty
- weakest skills
- target difficulty factors
- skill profile nodes
- skill graph edges
- recommended scenarios

### Write path

`POST /manager/reps/{rep_id}/adaptive-assignment`

Behavior:

- if no `scenario_id` is provided:
  - assign the top recommendation
- if a `scenario_id` is provided:
  - force that scenario while still attaching the adaptive plan

Adaptive assignments embed metadata in `assignments.retry_policy.adaptive_training`, including:

- source
- recommended difficulty
- weakest skills
- target difficulty factors
- selected scenario id
- recommendation score

This keeps the adaptive reasoning attached to the assignment without requiring new tables yet.

## Manager Analytics Possibilities

The current response shapes already support several manager analytics surfaces:

- rep readiness score over time
- weakest-skill leaderboard by team
- recommended difficulty band by rep
- scenario-to-skill coverage maps
- scenario recommendation acceptance rate
- skill improvement after adaptive assignments
- objection-handling and closing recovery trends

Potential future dashboard widgets:

- "Most at-risk skill" card per rep
- "Recommended next drill" panel
- "Difficulty progression" chart
- "Skill graph delta over last 7 sessions"
- "Scenario coverage gaps" by team

## Current Constraints

- The engine is derived, not persisted:
  - no dedicated `rep_skill_profiles` table yet
- It relies on current scorecard heuristics:
  - category quality is only as strong as the grading output
- Scenario focus is inferred:
  - there is no explicit scenario skill-tag taxonomy yet
- Adaptive difficulty is manager-facing today:
  - the rep app does not yet consume the plan directly

## Recommended Next Steps

1. Persist longitudinal skill snapshots after each graded session.
2. Add explicit `target_skills` and difficulty-factor metadata to scenarios.
3. Feed adaptive difficulty into the conversation runtime so scenario resistance can change even within the same scenario family.
4. Surface adaptive-plan data in the dashboard with charts and assignment controls.
