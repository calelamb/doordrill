# DoorDrill — Rep Post-Drill Experience
## Phase Suite: RD1 → RD2 → RD3 → RD4 → RD5

**Version:** 1.0
**Status:** Ready for Codex implementation
**Context:** QH and TH suites complete. The backend produces rich grading data (CategoryScoreV2
with rationale, improvement targets, behavioral signals, evidence turn IDs). None of it reaches
the rep. This suite closes that gap end-to-end.

---

## The Gap

After a drill, a rep sees:
- An overall score orb
- Five category bars with numbers only
- A few "KEY MOMENTS" highlights
- An AI summary paragraph
- Try Again / Back to Drills buttons

What CategoryScoreV2 actually produces that reps never see:
- `rationale_summary` — one-liner explaining WHY the score is that number
- `rationale_detail` — 400-char deep explanation with specific behavior references
- `improvement_target` — one concrete thing to fix, per category
- `behavioral_signals` — what the rep actually did (acknowledges_concern, pushes_close, etc.)
- `evidence_turn_ids` — which specific turns drove each category score

Additional gaps:
- No score trend over time (per category)
- No transcript to review
- No adaptive next-drill recommendation ("you should do difficulty 3 with objection handling focus")
- No streak or personal best indicators

The training loop doesn't close until reps can see exactly what happened, why it scored that way,
and what to do differently next time. That's what this suite builds.

---

## Phase Catalog

| Phase | Focus | Layer |
|-------|-------|-------|
| RD1 | Backend: enrich rep endpoints + transcript API | Backend |
| RD2 | ScoreScreen: category deep-dive + improvement targets | Mobile UI |
| RD3 | ScoreScreen: transcript tab with evidence highlighting | Mobile UI |
| RD4 | Trend chart + adaptive next-drill recommendation | Mobile UI + Backend |
| RD5 | Gamification: streaks, personal best, improvement badges | Mobile UI + Backend |

Build RD1 first — RD2–RD5 all depend on its new endpoints.

---

## Codex Execution Guide

1. Paste `BOOTSTRAP_PROMPT.md` first in every Codex thread.
2. Paste the phase prompt.
3. After backend phases: `cd backend && python -m pytest tests/ -x -q`
4. After mobile phases: verify in Expo simulator that all loading/empty/error states render.
5. Commit before moving to the next phase.

---

## Paste-Ready Phase Prompts

---

### PHASE RD1 — Backend: Rep endpoint enrichment + transcript + trend + adaptive plan

```
Bootstrap is loaded. QH and TH suites are complete.
Implement Phase RD1: enrich the rep-facing API to expose all grading depth, transcripts,
score trends, and adaptive next-drill recommendations.

Files to read first:
- backend/app/api/rep.py (full file)
- backend/app/schemas/scorecard.py (CategoryScoreV2, StructuredScorecardPayloadV2)
- backend/app/models/session.py (DrillSession, session_turns relationship if any)
- backend/app/models/scorecard.py (Scorecard — category_scores JSON, evidence_turn_ids)
- backend/app/services/adaptive_training_service.py (build_plan return shape)

Goals:

1. ENRICH GET /rep/sessions/{session_id}
   The existing response returns a flat scorecard dict. Extend it:

   a. CATEGORY DETAIL: When scorecard.scorecard_schema_version == "v2", parse
      category_scores as CategoryScoreV2 objects and include per-category:
        rationale_summary, rationale_detail, improvement_target, behavioral_signals,
        evidence_turn_ids (list of turn IDs where evidence was found for this category).
      When schema_version == "v1", return category_scores as-is (backward compatible).
      Add scorecard_schema_version to the response so the client knows which shape to expect.

   b. TRANSCRIPT: Query session_turns for the session, ordered by turn_index asc.
      Include in response as "transcript": list of:
        { turn_index: int, rep_text: str, ai_text: str, turn_id: str,
          objection_tags: list[str], emotion: str | null, stage: str | null }
      If no session_turns exist, return "transcript": [].

   c. IMPROVEMENT TARGETS: Compute a top-level "improvement_targets" list:
      Filter category_scores (v2 only) to categories where improvement_target is not null,
      sort by score ascending (weakest first), return top 3 as:
        [{ category: str, label: str, target: str, score: float }]
      category key maps to human label:
        opening→"Opening", pitch_delivery→"Pitch", objection_handling→"Objection Handling",
        closing_technique→"Closing", professionalism→"Professionalism"

2. ADD GET /rep/progress/trend
   New endpoint. Query params: rep_id (required), sessions (int, default 10, max 20).
   Returns last N scored sessions for the rep, per-category scores, for trend charting:
   {
     "sessions": [
       { "session_id": str, "started_at": str, "overall_score": float,
         "category_scores": { "opening": float, "pitch_delivery": float, ... } }
     ],
     "category_averages": { "opening": float, ... },
     "overall_trend": "improving" | "declining" | "stable"  // slope of last N overall scores
   }
   overall_trend: compute linear regression slope on overall_score over sessions.
     slope > 0.2 per session → "improving", slope < -0.2 → "declining", else "stable".

3. ADD GET /rep/plan
   New endpoint. Query param: rep_id (required).
   Calls adaptive_training_service.build_plan(db, rep_id=rep_id).
   Returns:
   {
     "focus_skills": list[str],
     "recommended_difficulty": int,
     "readiness_trajectory": { skill: { sessions_to_readiness: int, slope: float } },
     "next_scenario_suggestion": { "name": str, "difficulty": int, "reason": str } | null
   }
   For next_scenario_suggestion: query scenarios matching recommended_difficulty,
   pick the one whose weakness_tags most overlap with focus_skills. If none found, return null.
   Wrap in try/except — if build_plan fails, return empty defaults rather than 500.

4. EXTEND mobile types in backend response contracts
   Add to the /rep/sessions/{id} response schema:
   - transcript: list (as described above)
   - improvement_targets: list (as described above)
   - scorecard.scorecard_schema_version: string
   - per-category detail fields when v2

5. TESTS
   Write backend/tests/test_rep_api_enrichment.py:
   - test_session_detail_includes_transcript_when_turns_exist: seed session_turns,
     assert "transcript" in response with correct turn_index ordering.
   - test_session_detail_transcript_empty_when_no_turns: no session_turns, assert [].
   - test_session_detail_includes_improvement_targets_for_v2_scorecard: seed v2 scorecard
     with improvement_target on 3 categories, assert top 3 returned sorted by score asc.
   - test_session_detail_improvement_targets_empty_for_v1_scorecard.
   - test_progress_trend_returns_correct_session_count.
   - test_progress_trend_overall_trend_improving: seed sessions with rising scores, assert "improving".
   - test_rep_plan_returns_defaults_on_no_history: no prior sessions, assert valid empty plan.

6. Run pytest tests/ -x -q. All tests must pass.
```

---

### PHASE RD2 — Mobile: ScoreScreen category deep-dive + improvement targets

```
Bootstrap is loaded. Phase RD1 is complete.
Implement Phase RD2: surface CategoryScoreV2 depth in the ScoreScreen.

Files to read first:
- mobile/src/screens/ScoreScreen.tsx (full file)
- mobile/src/types.ts (Scorecard type, RepSessionDetail)
- mobile/src/services/api.ts (fetchRepSession)
- mobile/src/theme/tokens.ts (color tokens)

Goals:

1. UPDATE TYPES (mobile/src/types.ts)
   Extend Scorecard type:
     category_scores: Record<string, CategoryScoreDetail>
     improvement_targets: ImprovementTarget[]
     scorecard_schema_version: string

   Add:
   type CategoryScoreDetail = {
     score: number
     rationale_summary?: string
     rationale_detail?: string
     improvement_target?: string | null
     behavioral_signals?: string[]
     evidence_turn_ids?: string[]
     confidence?: number
   }
   type ImprovementTarget = {
     category: string
     label: string
     target: string
     score: number
   }

2. EXPANDABLE CategoryBar COMPONENT
   Replace the existing CategoryBar component with ExpandableCategoryBar.
   Default state: same as current (label + score + animated bar).
   Tapped state: expands with spring animation (react-native-reanimated useAnimatedStyle +
   withSpring) to reveal:
     a. RATIONALE ROW: rationale_summary in a muted caption style. If rationale_detail
        differs meaningfully (length > rationale_summary + 20 chars), show a "More" link
        that expands further to rationale_detail.
     b. IMPROVEMENT TARGET ROW (only if improvement_target exists): styled as a small
        action-item chip in amber/orange: "→ {improvement_target}" — make it visually
        distinct, like a pill with a right-arrow icon.
     c. BEHAVIORAL SIGNALS ROW (only if behavioral_signals non-empty): horizontal scroll
        of small rounded chips. Green chips for positive signals (acknowledges_concern,
        builds_rapport, explains_value, provides_proof, reduces_pressure, personalizes_pitch,
        invites_dialogue), red chips for negative signals (pushes_close, dismisses_concern,
        ignores_objection, high_difficulty_backfire).
     d. EVIDENCE TURNS ROW (only if evidence_turn_ids non-empty): compact label
        "Evidence: Turn {n}, Turn {m}" — muted caption. Tapping a turn ID scrolls to
        or highlights that turn in the transcript tab (pass via navigation or shared state).
   Only one category can be expanded at a time — collapse others when one opens.
   Wrap the expanded content in a FadeInDown animation.

3. IMPROVEMENT TARGETS SECTION
   Add a new section "WHAT TO WORK ON" above the "KEY MOMENTS" section.
   Only render when improvement_targets array is non-empty (v2 scorecards only).
   Show up to 3 items. Each item:
     - Left: colored circle with category initial (O, P, OH, C, PR)
     - Center: ImprovementTarget.label in bold, ImprovementTarget.target below in normal weight
     - Right: score badge (same scoreBand color coding as category bars)
   Style: same glass card as categoriesContainer.
   Include a subtitle "Focus on these in your next drill" under the section header.

4. WEAKNESS TAGS
   Below the FEEDBACK section, if scorecard.weakness_tags is non-empty, add:
   "AREAS TO WATCH" section with horizontal scroll of red-tinted rounded chips.
   Each chip: weakness tag text formatted (replace underscores with spaces, title case).

5. STATE HANDLING
   All new sections handle: empty state gracefully (hidden when data absent), v1 scorecard
   gracefully (expandable bars show score only, no deep-dive content, no WHAT TO WORK ON
   section), loading state (skeleton shimmer on expanded content while parent data loads).

6. No new backend calls needed — all data comes from the already-enriched fetchRepSession.
   No new tests required for mobile, but verify in simulator:
   - Tap each category bar to expand/collapse
   - Verify only one expands at a time
   - Verify WHAT TO WORK ON section appears for v2 scorecard
   - Verify the section is absent for v1 scorecard
```

---

### PHASE RD3 — Mobile: Transcript tab with evidence highlighting

```
Bootstrap is loaded. Phase RD2 is complete.
Implement Phase RD3: add a Transcript tab to ScoreScreen showing the full drill conversation
with evidence turns highlighted.

Files to read first:
- mobile/src/screens/ScoreScreen.tsx (full file — especially state, data loading, and ScrollView structure)
- mobile/src/types.ts (Transcript type added in RD1)

Goals:

1. TAB SWITCHER
   Replace the current single-view ScoreScreen with a two-tab layout:
   Tab 1: "Scorecard" (all existing content unchanged)
   Tab 2: "Transcript" (new content — see below)

   Tab switcher UI: two pill buttons side by side at the top of the screen, below
   the hero score orb. Active tab: filled with colors.accent, white text.
   Inactive tab: outlined, muted text. Animate active indicator with withSpring.
   Switching tabs should not re-fetch — all data is already loaded.

2. COLLECT EVIDENCE TURN IDs
   From the scorecard, gather all evidence_turn_ids:
   - Top-level scorecard.evidence_turn_ids
   - Per-category evidence_turn_ids from CategoryScoreDetail (v2 only)
   Build a map: turnId → list of category labels that cite it.
   Example: { "turn-uuid-3": ["Objection Handling", "Closing"] }

3. TRANSCRIPT TAB CONTENT
   Render transcript from data.transcript (populated by RD1 endpoint).
   Empty state: "Transcript not available for this session" with a muted icon.
   Loading: show ActivityIndicator while data loads.

   Each turn renders as a conversation bubble:
     REP bubble (right-aligned, accent-tinted background):
       - Label: "You" in bold caption
       - Text: turn.rep_text
     HOMEOWNER bubble (left-aligned, white/glass background):
       - Label: "Homeowner" in bold caption
       - Text: turn.ai_text (may be empty for the final turn — hide if empty)
     Between turns: subtle turn number label centered ("Turn 3")

   EVIDENCE HIGHLIGHTING:
   If a turn's turn_id appears in the evidence map, render the rep bubble with:
     - Left border: 3px solid colors.accent
     - Below the bubble text: horizontal scroll of small category chips
       (the categories that cited this turn as evidence) — same chip style as behavioral signals
   This visually connects the score to the moment it happened.

   EMOTION + STAGE ANNOTATIONS:
   If turn.emotion is not null, show a small emotion chip (neutral/skeptical/annoyed/hostile →
   gray/yellow/orange/red tint respectively) in the turn header row.
   If turn.stage is not null, show it as a muted caption in the turn header.

4. SHARE / COPY TRANSCRIPT
   Add a share icon button (top-right corner of transcript tab, Share icon from lucide).
   On press: format the transcript as plain text and trigger Share sheet (use expo-sharing or
   React Native Share API). Format:
     "[DoorDrill Transcript] {scenario name} — {date}\n\n
      Turn 1\nYou: {rep_text}\nHomeowner: {ai_text}\n\n
      Turn 2\n..."

5. SCROLL TO EVIDENCE
   From the Scorecard tab, when a rep taps a turn reference (evidence_turn_ids chips added in RD2),
   switch to the Transcript tab AND scroll to that turn. Implement via:
   - A shared ref to the transcript ScrollView
   - A Map of turn_id → y-offset (computed on layout with onLayout)
   - On evidence turn tap: switch tab, then scrollTo({ y: offset, animated: true })

6. No new backend calls or tests required.
   Verify in simulator:
   - Transcript tab shows full conversation
   - Evidence turns have visible left border and category chips
   - Share button produces correctly formatted text
   - Tapping evidence turn IDs from Scorecard tab scrolls correctly
```

---

### PHASE RD4 — Mobile + Backend: Score trend chart + adaptive next-drill card

```
Bootstrap is loaded. Phase RD3 is complete.
Implement Phase RD4: score trend visualization and adaptive next-drill recommendation.

Files to read first:
- mobile/src/screens/HistoryScreen.tsx (full file)
- mobile/src/screens/ScoreScreen.tsx (full file — especially CTA section)
- mobile/src/services/api.ts
- mobile/src/types.ts

Goals:

1. ADD API CALLS (mobile/src/services/api.ts)
   Add:
   export async function fetchRepTrend(repId: string, sessions = 10): Promise<RepTrend>
   export async function fetchRepPlan(repId: string): Promise<RepPlan>

   Add types to mobile/src/types.ts:
   type RepTrend = {
     sessions: Array<{
       session_id: string
       started_at: string
       overall_score: number
       category_scores: Record<string, number>
     }>
     category_averages: Record<string, number>
     overall_trend: "improving" | "declining" | "stable"
   }
   type RepPlan = {
     focus_skills: string[]
     recommended_difficulty: number
     readiness_trajectory: Record<string, { sessions_to_readiness: number; slope: number }>
     next_scenario_suggestion: { name: string; difficulty: number; reason: string } | null
   }

2. HISTORY SCREEN — TREND CHART
   Add a trend chart section at the top of HistoryScreen, above the session list.
   Fetch with fetchRepTrend(repId, 8) on mount (parallel with history fetch).

   Chart: a compact multi-line sparkline using Recharts LineChart (already available).
   One line per category (5 lines), x-axis = session index, y-axis = 0–10.
   Colors: accent green for objection_handling (most important), muted palette for others.
   Show category labels in a horizontal legend below the chart (small chips with color dots).
   Chart height: 140px.

   Above chart: a trend indicator row showing overall_trend:
     "improving" → green arrow up + "Overall: Improving"
     "declining" → red arrow down + "Overall: Needs Attention"
     "stable" → gray dash + "Overall: Steady"

   Below chart: category_averages as a horizontal row of small stat chips:
     "Opening 7.2  Pitch 6.8  Obj. 5.1  Closing 6.4  Prof. 8.0"
   Weakest category (lowest average) chip is highlighted in amber.

   Loading state: a shimmer skeleton rect at the chart's height.
   Empty state (fewer than 2 scored sessions): show "Complete 2 drills to see your trend" instead.

3. SCORESCREEN — NEXT DRILL CARD
   Replace or extend the existing CTA row at the bottom of ScoreScreen.
   Fetch fetchRepPlan(repId) on mount (parallel with session detail fetch).

   When plan is loaded and next_scenario_suggestion is not null, render a "NEXT DRILL"
   card above the Try Again / Back to Drills buttons:
   Glass card (same style as other cards) with:
     - Header: "RECOMMENDED NEXT DRILL" section label
     - Scenario name in bold (next_scenario_suggestion.name)
     - Difficulty dots row (filled dots up to recommended_difficulty, empty dots to 5)
     - Focus skills as green chips (plan.focus_skills — format as readable labels)
     - Reason: next_scenario_suggestion.reason in muted caption
     - CTA button: "Start This Drill →" → navigates to PreSession with the suggested scenario_id
       (fetch scenario_id from scenarios list by name match, or add scenario_id to the suggestion
       in RD1's next_scenario_suggestion shape)

   Update RD1's GET /rep/plan to include scenario_id in next_scenario_suggestion:
     { "name": str, "scenario_id": str | null, "difficulty": int, "reason": str }

   When plan is null / loading / focus_skills empty: hide the card entirely (never show skeleton
   for the next-drill card — it's bonus content, not primary).

4. SCORESCREEN — READINESS TRAJECTORY SNIPPET
   In the PERFORMANCE BREAKDOWN section, below the category bars, add a small readiness hint
   when plan data is loaded and readiness_trajectory is non-empty:
   "At this rate, you'll hit target on Objection Handling in ~{N} more drills"
   Show only the weakest focus skill's trajectory. Muted caption style. Animated FadeInDown.
   Hide if N is null or > 20 (not meaningful).

5. No new backend tests needed (RD1 already covers the new endpoints).
   Verify in simulator:
   - History screen shows trend chart after 2+ sessions
   - Trend indicator reflects actual score direction
   - ScoreScreen shows Next Drill card when plan returns a suggestion
   - "Start This Drill" button navigates correctly
```

---

### PHASE RD5 — Mobile: Gamification layer (streaks, personal best, improvement badges)

```
Bootstrap is loaded. Phase RD4 is complete.
Implement Phase RD5: streak tracking, personal best badges, and category improvement indicators.

Files to read first:
- mobile/src/screens/ScoreScreen.tsx (full file)
- mobile/src/screens/AssignmentsScreen.tsx (full file)
- mobile/src/services/api.ts
- mobile/src/types.ts
- backend/app/api/rep.py (GET /rep/progress endpoint)

Goals:

1. BACKEND: ENRICH GET /rep/progress
   Current response: { rep_id, rep_name, session_count, scored_session_count, average_score }
   Add:
   - streak_days: int — count of consecutive calendar days (in local time) on which the rep
     completed at least one scored session. Reset to 0 if yesterday had none.
   - personal_best: float | null — highest overall_score across all sessions
   - personal_best_session_id: str | null
   - most_improved_category: str | null — category with the largest positive average delta
     between the rep's first 3 sessions vs their last 3 sessions (min 6 sessions to compute)
   - most_improved_delta: float | null

   Write test_rep_progress_streak.py:
   - test_streak_counts_consecutive_days
   - test_streak_resets_on_gap_day
   - test_personal_best_returns_highest_score
   - test_most_improved_category_correct

2. UPDATE RepProgress TYPE (mobile/src/types.ts)
   Add streak_days, personal_best, personal_best_session_id,
   most_improved_category, most_improved_delta to RepProgress type.

3. SCORESCREEN — PERSONAL BEST BADGE
   After session data loads, compare scorecard.overall_score to repProgress.personal_best
   (fetch fetchRepProgress on ScoreScreen mount in parallel with session detail).
   If overall_score >= personal_best (or personal_best was null — this is the first scored session):
     Show a "NEW PERSONAL BEST" banner between the hero orb and the score bar.
     Style: gold/amber gradient pill, star icon (Star from lucide-react-native), bold text.
     Animate in with FadeInDown + a Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).

4. SCORESCREEN — CATEGORY IMPROVEMENT BADGE
   If repProgress.most_improved_category is not null and most_improved_delta > 1.0:
     Add a "MOST IMPROVED" chip below the PERFORMANCE BREAKDOWN section header:
     "Most improved: {categoryLabel} +{delta.toFixed(1)} vs your first sessions"
     Style: green tinted chip with TrendingUp icon (lucide). Animated FadeInDown.

5. ASSIGNMENTS SCREEN — STREAK BANNER
   Fetch fetchRepProgress on AssignmentsScreen mount (already fetches assignments).
   If streak_days >= 2: show a compact streak banner below the screen header:
     "🔥 {streak_days}-day streak — keep it going!"
     Style: amber/warm tinted rounded pill. FadeInDown animation on first render.
   If streak_days == 0 and last session was yesterday: show a softer nudge:
     "Drill today to start a streak"
   If streak_days >= 7: upgrade the fire emoji and text:
     "🔥 {streak_days}-day streak — you're on fire!"

6. PROFILE SCREEN — STATS ROW
   Add a stats row to ProfileScreen (currently just shows name/avatar/email):
   Three stat chips in a horizontal row:
     - "Best Score: {personal_best.toFixed(1)}" or "—" if null
     - "{streak_days}-day streak" with fire icon
     - "Most Improved: {categoryLabel}" or "—" if null
   Style: glassmorphism row, same card styling as the rest of the app.

7. Run pytest tests/ -x -q. All tests must pass.
   Verify in simulator:
   - Personal best banner fires on new high score with haptic
   - Streak banner appears after 2 consecutive drill days
   - Profile stats row renders correctly in empty and populated states
```

---

## Commit Messages

```
feat(rep): RD1 — enrich rep session endpoint + transcript + trend + adaptive plan endpoints
feat(rep): RD2 — ScoreScreen category deep-dive + improvement targets + weakness tags
feat(rep): RD3 — ScoreScreen transcript tab with evidence highlighting + share
feat(rep): RD4 — History trend chart + ScoreScreen next-drill adaptive recommendation
feat(rep): RD5 — streak tracking, personal best badge, improvement badges, profile stats
```

---

## What the Rep Experience Looks Like After This Suite

**After RD1**: All the grading intelligence is available over the API. Nothing visible to rep yet but everything is wired.

**After RD2**: Tapping "Objection Handling: 5.1" expands to show exactly why — "You acknowledged the price concern but pivoted too quickly to close before building trust." Below it: "→ Address the specific objection before mentioning scheduling." Behavioral signal chips show what they did right and wrong. The "WHAT TO WORK ON" section shows the 3 weakest targets front and center.

**After RD3**: Reps can scroll through their exact conversation. Evidence turns — the moments that drove their score — have a green left border and category labels. They can see "Turn 3 is what hurt my Objection Handling score" and study exactly what they said. They can share the transcript to review with a manager or teammate.

**After RD4**: History screen opens to a trend chart. "Objection Handling was 4.2 five sessions ago and is now 6.1 — improving." ScoreScreen ends with "RECOMMENDED NEXT DRILL: Hostile Homeowner, Difficulty 4, focusing on Objection Handling." One tap to start it.

**After RD5**: "NEW PERSONAL BEST" banner fires with a haptic on a record score. AssignmentsScreen shows a streak banner after back-to-back drill days. Profile page shows personal best, streak, and most-improved category. This is what makes a rep open the app on a day they didn't have a scheduled drill.
