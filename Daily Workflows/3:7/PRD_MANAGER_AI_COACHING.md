# PRD: Manager AI Coaching — Depth Layer
**Version:** 1.0
**Status:** Ready for Codex implementation
**Depends on:** Transcript Pipeline (TP1–TP4), Grading Engine V2 (G1–G3), Training Loop (T1–T4)

---

## What This PRD Builds

The `ManagerAiCoachingService` exists and is wired up, but it operates on surface-level data — raw scorecard averages and weakness tag counts. It has no awareness of the adaptive skill profile, no forward-looking trajectory, no 1:1 prep intelligence, and no team-level weekly synthesis.

This PRD adds four targeted upgrades that turn the coaching service from a data summarizer into a genuine management copilot:

1. **Deeper rep insight** — wire the full adaptive skill profile + override signal into `generate_rep_insight`, and add a predictive readiness trajectory
2. **1:1 prep card** — auto-generated briefing a manager reads before sitting down with a rep
3. **Weekly team briefing** — Monday morning synthesis: who improved, who's sliding, what to focus on as a team
4. **Frontend surfacing** — update `CoachingLabPage.tsx` and add a `OneOnOnePrepCard` component

---

## Data Available (Use All of It)

The coaching service currently ignores most of the system's richest signals. After the infrastructure PRDs are complete, the following is available:

| Signal | Source | Currently Used |
|--------|--------|----------------|
| Scorecard category averages | `scorecards.category_scores` | ✅ |
| Weakness tags | `scorecards.weakness_tags` | ✅ |
| Overall score trend | `scorecards.overall_score` | ✅ |
| Adaptive skill profile (propagated scores, confidence, trend per skill) | `AdaptiveTrainingService.build_plan()` | ❌ |
| Emotion recovery patterns | `AdaptiveTrainingService._build_session_snapshot()` | ❌ |
| Objection load per session | `session_turns.objection_tags` | ❌ |
| Manager override history (how often, how much delta) | `OverrideLabel` model | ❌ |
| Recommended difficulty + difficulty tuning outcomes | `AdaptiveRecommendationOutcome` | ❌ |
| Fact warehouse rep daily aggregates | `fact_rep_daily` | ❌ |
| Recent coaching notes written by manager | `manager_coaching_notes` | ❌ (team summary only) |
| Enriched turn emotion/resistance columns | `session_turns.emotion_before/after`, `resistance_level` | ❌ |

---

## Phase C1 — Deepen Rep Insight + Predictive Trajectory

### Goals

1. In `generate_rep_insight()`, after querying recent sessions, call `AdaptiveTrainingService().build_plan(db, rep_id=rep.id)` and merge the result into the prompt context. Add the following to the Claude prompt:
   - Full skill profile (score, trend, confidence per skill)
   - Recommended difficulty (what the engine thinks they're ready for)
   - Weakest skills from the adaptive engine (not just weakness tags)
   - Emotion recovery average across recent sessions

2. Pull override signal: query `OverrideLabel` where `rep_id = rep.id` in the period. Add to prompt:
   - Override count
   - Mean override delta (positive = AI was grading too low, negative = too high)
   - Most overridden category (if pattern exists)

3. Add predictive readiness trajectory to `generate_rep_insight()`. Implement a pure-Python function `_compute_readiness_trajectory(snapshots, skill_profile)` in the service:
   - Compute linear regression slope per skill using existing session snapshots
   - Project each skill score forward: `projected_score = current_score + (slope * sessions_to_project)`
   - Determine sessions until all weakest skills exceed `READINESS_THRESHOLD = 7.0`
   - Return `{"sessions_to_readiness": int | None, "trajectory_per_skill": {skill: projected_score}}`
   - If slope is flat or negative for weakest skills, return `sessions_to_readiness: None`

4. Extend `RepInsightContent` schema in `backend/app/schemas/manager_ai.py`:
   - Add `readiness_trajectory: dict` (sessions_to_readiness, trajectory_per_skill)
   - Add `override_signal: dict` (override_count, mean_delta, most_overridden_category)
   - Add `adaptive_skill_profile: list[dict]` (the full skill nodes from build_plan)

5. Update the Claude prompt for rep insight to use all new context. The prompt should now produce a meaningfully richer `coaching_script` that references specific skill scores and trajectory, not just generic weakness tags.

6. Tests:
   - `test_rep_insight_includes_adaptive_profile.py` — assert `adaptive_skill_profile` is present and non-empty in the response
   - `test_readiness_trajectory_computation.py` — unit test `_compute_readiness_trajectory` directly with known snapshot data, assert correct sessions_to_readiness output
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase C2 — 1:1 Prep Card

### What It Is

A manager clicks "Prep for 1:1" on any rep card. Within 3 seconds they get a structured card that tells them exactly what to walk into the meeting with. This is the single most time-saving feature a manager can have.

### Goals

1. Add `generate_one_on_one_prep(db, *, rep, manager, period_days)` to `ManagerAiCoachingService`. It should:
   - Call `AdaptiveTrainingService().build_plan(db, rep_id=rep.id)` for current skill state
   - Query last 5 sessions with scorecards + coaching notes + override labels
   - Query `AdaptiveRecommendationOutcome` for recent success/failure patterns
   - Build a prompt that asks Claude to return:
     ```json
     {
       "discussion_topics": [
         {"topic": "string", "evidence": "1 sentence of specific data backing it up", "suggested_opener": "exact words manager can say"}
       ],
       "strength_to_acknowledge": {"skill": "string", "what_to_say": "1-2 sentences"},
       "pattern_to_challenge": {"skill": "string", "pattern": "description", "what_to_say": "1-2 sentences"},
       "suggested_next_scenario": {"scenario_type": "string", "difficulty": int, "rationale": "1 sentence"},
       "readiness_summary": "one sentence on where this rep stands overall right now"
     }
     ```
   - `discussion_topics` should be exactly 3 items, ordered by priority
   - Everything should reference actual numbers ("Your closing score dropped from 6.8 to 5.4 over 3 sessions"), not generic coaching platitudes

2. Add `OneOnOnePrepRequest` and `OneOnOnePrepResponse` to `backend/app/schemas/manager_ai.py`

3. Add endpoint to `backend/app/api/manager.py`:
   ```
   POST /manager/reps/{rep_id}/one-on-one-prep
   Body: {"manager_id": str, "period_days": int = 14}
   ```

4. Cache result with TTL of 2 hours (reuse `rep_insight_cache` pattern)

5. Tests:
   - `test_one_on_one_prep_structure.py` — call the endpoint, assert response has all 3 discussion topics with evidence, a strength, a challenge pattern, and a scenario suggestion
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase C3 — Weekly Team Briefing

### What It Is

A single API call returns a structured Monday morning brief for the manager. Who had a strong week. Who's sliding. What the team's shared weakness is right now. What to say in the next team huddle. No reading 10 rep profiles — one card, 30 seconds, ready to act.

### Goals

1. Add `generate_weekly_team_briefing(db, *, manager, reps)` to `ManagerAiCoachingService`:
   - For each rep in `reps`, query sessions from the last 7 days with scorecards
   - For each rep with at least 1 session, call `AdaptiveTrainingService().build_plan(db, rep_id=rep.id)` — cap at 8 reps to avoid latency (process top 8 by session count)
   - Query `fact_rep_daily` for the last 7 days for warehouse-aggregated skill trends
   - Identify: most improved rep, most declined rep, most common team-wide weakness tag this week
   - Build prompt asking Claude to return:
     ```json
     {
       "team_pulse": "2 sentences on overall team momentum this week",
       "standout_rep": {"name": "string", "why": "1 sentence with specific stat"},
       "needs_attention": [{"name": "string", "concern": "1 sentence with specific stat"}],
       "shared_weakness": {"skill": "string", "team_average": float, "note": "1 sentence"},
       "huddle_topic": {"topic": "string", "suggested_talking_points": ["string", "string", "string"]},
       "manager_action_items": ["string", "string"]
     }
     ```
   - `needs_attention` should be at most 2 reps
   - `manager_action_items` should be concrete ("Assign Marcus a difficulty-3 objection scenario before Friday") not vague ("Monitor team performance")

2. Add `WeeklyTeamBriefingResponse` to `backend/app/schemas/manager_ai.py`

3. Add endpoint to `backend/app/api/manager.py`:
   ```
   POST /manager/team/weekly-briefing
   Body: {"manager_id": str}
   ```

4. Cache result with TTL of 6 hours per manager

5. Tests:
   - `test_weekly_team_briefing_structure.py` — seed 2 reps with sessions from the last 7 days, call endpoint, assert response has team_pulse, standout_rep, shared_weakness, huddle_topic, and at least 1 manager_action_item
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase C4 — Frontend Surfacing

### Goals

1. Update `dashboard/src/pages/CoachingLabPage.tsx`:
   - Add a "Weekly Briefing" card at the top of the page that calls `POST /manager/team/weekly-briefing` on load and renders:
     - Team pulse headline
     - Standout rep chip
     - Needs-attention rep chips (with warning color)
     - Shared weakness bar
     - Huddle topic with talking points (collapsible)
     - Action items as a checklist

2. Add `dashboard/src/components/OneOnOnePrepCard.tsx`:
   - Triggered from rep card "Prep 1:1" button
   - Renders as a slide-out panel or modal
   - Shows: readiness summary, 3 discussion topics (each with evidence + opener), strength to acknowledge, pattern to challenge, suggested next scenario
   - Include a "Copy to clipboard" button that formats the card as plain text for pasting into notes

3. Update `RepProgressPage.tsx` or `RepPanel.tsx`:
   - Add readiness trajectory visualization: a simple projected score line per weakest skill showing where the rep lands in N sessions
   - Show override signal: "Manager has adjusted AI scores X times for this rep — avg delta Y"

4. All new components must handle loading, empty, and error states

5. No new tests required for frontend, but all existing dashboard tests must still pass if any exist

---

## Paste-Ready Codex Prompts

### PHASE C1 — Deepen rep insight + predictive trajectory

```
Bootstrap is loaded. The infrastructure PRDs (TP1–T4) are complete. Implement Phase C1 from Daily Workflows/3:7/PRD_MANAGER_AI_COACHING.md.

Goals:
1. In generate_rep_insight(), call AdaptiveTrainingService().build_plan() and merge the full adaptive skill profile, recommended difficulty, and emotion recovery into the Claude prompt context.
2. Pull OverrideLabel history for the rep and add override_count, mean_delta, and most_overridden_category to the prompt.
3. Implement _compute_readiness_trajectory(snapshots, skill_profile) — linear regression slope per skill, project to READINESS_THRESHOLD = 7.0, return sessions_to_readiness and trajectory_per_skill.
4. Extend RepInsightContent schema with readiness_trajectory, override_signal, adaptive_skill_profile fields.
5. Tests: test_rep_insight_includes_adaptive_profile.py, test_readiness_trajectory_computation.py.
6. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE C2 — 1:1 prep card

```
Bootstrap is loaded. Phase C1 is complete. Implement Phase C2 from Daily Workflows/3:7/PRD_MANAGER_AI_COACHING.md.

Goals:
1. Add generate_one_on_one_prep(db, *, rep, manager, period_days) to ManagerAiCoachingService.
2. Pull adaptive plan, last 5 sessions, coaching notes, override labels, and AdaptiveRecommendationOutcome for the rep.
3. Claude returns: 3 discussion_topics (with evidence + suggested_opener), strength_to_acknowledge, pattern_to_challenge, suggested_next_scenario, readiness_summary.
4. Add OneOnOnePrepRequest/Response schemas.
5. Add POST /manager/reps/{rep_id}/one-on-one-prep endpoint.
6. Tests: test_one_on_one_prep_structure.py.
7. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE C3 — Weekly team briefing

```
Bootstrap is loaded. Phase C2 is complete. Implement Phase C3 from Daily Workflows/3:7/PRD_MANAGER_AI_COACHING.md.

Goals:
1. Add generate_weekly_team_briefing(db, *, manager, reps) to ManagerAiCoachingService.
2. For each rep (cap 8), call build_plan() and query last 7 days sessions + fact_rep_daily aggregates.
3. Claude returns: team_pulse, standout_rep, needs_attention (max 2), shared_weakness, huddle_topic with talking points, manager_action_items (concrete, not vague).
4. Add WeeklyTeamBriefingResponse schema.
5. Add POST /manager/team/weekly-briefing endpoint with 6-hour cache.
6. Tests: test_weekly_team_briefing_structure.py.
7. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE C4 — Frontend surfacing

```
Bootstrap is loaded. Phase C3 is complete. Implement Phase C4 from Daily Workflows/3:7/PRD_MANAGER_AI_COACHING.md.

Goals:
1. Update CoachingLabPage.tsx — add Weekly Briefing card at top: team pulse, standout rep, needs-attention chips, shared weakness, huddle topic (collapsible), action items checklist.
2. Add OneOnOnePrepCard.tsx — slide-out panel with discussion topics (evidence + opener), strength, pattern to challenge, suggested scenario, copy-to-clipboard button.
3. Update RepProgressPage.tsx or RepPanel.tsx — add readiness trajectory line chart (projected skill scores), and override signal summary.
4. All components handle loading/empty/error states.
```

---

## Cross-PRD Notes

- C1 depends on `AdaptiveTrainingService.build_plan()` — already built
- C1 depends on `OverrideLabel` model — built in T1
- C2 depends on `AdaptiveRecommendationOutcome` — built in T3
- C3 depends on `fact_rep_daily` warehouse table — built in W1
- C4 depends on C1–C3 endpoints being available
