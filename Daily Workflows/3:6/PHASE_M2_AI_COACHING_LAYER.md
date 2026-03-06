# PHASE M2 — AI Coaching Layer
# Goal: Make the manager smarter. Claude analyzes rep data and generates specific,
# actionable coaching recommendations. Managers stop guessing and start coaching with precision.

---

## Files to read first (required before touching anything)

- `dashboard/src/lib/types.ts` — `RepProgress`, `CoachingAnalyticsResponse`, `ReplayResponse`, `ManagerCoachingNote`
- `dashboard/src/lib/api.ts` — `fetchRepProgress`, `fetchReplay`, `createCoachingNote`
- `dashboard/src/pages/CoachingLabPage.tsx` — current coaching lab implementation
- `dashboard/src/pages/RepProgressPage.tsx` — individual rep view
- `dashboard/src/pages/ManagerReplayPage.tsx` — session replay view
- `backend/app/routers/manager.py` — existing manager router, add new endpoints here
- `backend/app/services/grading.py` — see how Claude Opus is called for grading, follow the same pattern

---

## Part 1: Backend — AI Coaching Endpoints

### New endpoint: POST /manager/ai/rep-insight

Add to `backend/app/routers/manager.py`.

**Request body:**
```python
class RepInsightRequest(BaseModel):
    manager_id: str
    rep_id: str
    period_days: int = 30
```

**Logic:**
1. Query the database for the rep's last N sessions (up to 30), including:
   - `overall_score`, `category_scores`, `weakness_tags`, `highlights`, `ai_summary` from scorecards
   - `scenario_name` and `scenario_difficulty` from joined scenario table
2. Compute: average score per category, top 3 weakness_tags by frequency, score trend (slope of last 10 sessions), sessions below 6.0 count
3. Build a Claude prompt (use Anthropic Python SDK, same pattern as grading service):

```
You are an expert D2D sales coach analyzing a rep's training data.

Rep data:
- Name: {rep_name}
- Sessions analyzed: {session_count}
- Average score: {avg_score}/10
- Score trend: {trend_direction} ({trend_delta:+.1f} over last 10 sessions)
- Category averages: Opening {opening}/10, Pitch {pitch}/10, Objection Handling {objection}/10, Closing {closing}/10, Professionalism {professionalism}/10
- Top weakness tags: {weakness_tags}
- Recent AI session summaries:
  {last_3_summaries}

Provide a coaching analysis in this exact JSON format:
{
  "headline": "one sentence diagnosis (max 15 words)",
  "primary_weakness": "the single most important area to fix",
  "root_cause": "why this weakness likely exists (2 sentences)",
  "drill_recommendation": "specific scenario type and difficulty to assign next",
  "coaching_script": "3-4 sentences the manager should say directly to this rep",
  "expected_improvement": "what should improve and in how many sessions if coaching works"
}
```

4. Parse the JSON response, return as `RepInsightResponse`
5. Cache in Redis for 1 hour with key `rep_insight:{rep_id}:{period_days}`

**Response schema:**
```python
class RepInsightResponse(BaseModel):
    rep_id: str
    rep_name: str
    generated_at: str  # ISO timestamp
    headline: str
    primary_weakness: str
    root_cause: str
    drill_recommendation: str
    coaching_script: str
    expected_improvement: str
    data_summary: dict  # the raw stats used to generate this
```

---

### New endpoint: POST /manager/ai/session-annotations

Add to `backend/app/routers/manager.py`.

**Request body:**
```python
class SessionAnnotationRequest(BaseModel):
    manager_id: str
    session_id: str
```

**Logic:**
1. Fetch the full transcript from the session (transcript_turns)
2. Fetch the existing scorecard (weakness_tags, highlights, category_scores)
3. Build a Claude prompt that analyzes each transcript turn and identifies the 3-5 most instructive moments:

```
You are a D2D sales training coach. Analyze this sales call transcript and identify the 3-5 most instructive moments — moments where the rep either did something particularly well or made a mistake that should be discussed in coaching.

Transcript:
{transcript_turns formatted as: [TURN {n}] REP: "{text}" | AI: "{text}"}

Scorecard context:
- Overall score: {overall_score}/10
- Weakness tags: {weakness_tags}
- Highlights: {highlights}

Return JSON array:
[
  {
    "turn_id": "the turn_id of the moment",
    "type": "strength" | "weakness",
    "label": "short label (max 6 words)",
    "explanation": "what the rep did and why it matters (2-3 sentences)",
    "coaching_tip": "what the rep should have said or done instead (1-2 sentences, only for weakness type)"
  }
]
```

4. Return annotations sorted by turn_index
5. Cache in Redis for 4 hours with key `session_annotations:{session_id}`

**Response schema:**
```python
class SessionAnnotation(BaseModel):
    turn_id: str
    type: Literal["strength", "weakness"]
    label: str
    explanation: str
    coaching_tip: Optional[str]

class SessionAnnotationsResponse(BaseModel):
    session_id: str
    generated_at: str
    annotations: List[SessionAnnotation]
```

---

## Part 2: Frontend — Types

Add to `dashboard/src/lib/types.ts`:

```typescript
export type RepInsightResponse = {
  rep_id: string;
  rep_name: string;
  generated_at: string;
  headline: string;
  primary_weakness: string;
  root_cause: string;
  drill_recommendation: string;
  coaching_script: string;
  expected_improvement: string;
  data_summary: Record<string, unknown>;
};

export type SessionAnnotation = {
  turn_id: string;
  type: "strength" | "weakness";
  label: string;
  explanation: string;
  coaching_tip?: string | null;
};

export type SessionAnnotationsResponse = {
  session_id: string;
  generated_at: string;
  annotations: SessionAnnotation[];
};
```

---

## Part 3: Frontend — API functions

Add to `dashboard/src/lib/api.ts`:

```typescript
export async function fetchRepInsight(
  managerId: string,
  repId: string,
  periodDays = 30
): Promise<RepInsightResponse> {
  return requestJson<RepInsightResponse>(
    `/manager/ai/rep-insight`,
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId, rep_id: repId, period_days: periodDays }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchSessionAnnotations(
  managerId: string,
  sessionId: string
): Promise<SessionAnnotationsResponse> {
  return requestJson<SessionAnnotationsResponse>(
    `/manager/ai/session-annotations`,
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId, session_id: sessionId }),
    },
    { userId: managerId, role: "manager" }
  );
}
```

---

## Part 4: Frontend — RepProgressPage AI Insight Panel

Add an "AI Coach" panel to `dashboard/src/pages/RepProgressPage.tsx`.

**Design:**
- Placed below the radar chart, above the session history table
- Glassmorphism card: `bg-white/40 backdrop-blur-2xl border border-white/30 rounded-2xl p-6`
- Header: sparkle icon + "AI Coach Analysis" + "Refresh" button (small, ghost variant) + timestamp "Generated 2h ago"
- Skeleton state while loading (3 text placeholder rows)
- Error state: "Could not generate analysis. Try refreshing." with retry button

**Content layout:**
```
┌─────────────────────────────────────────────────┐
│ ✦ AI Coach Analysis              [Refresh] 2h ago│
│                                                   │
│ DIAGNOSIS                                         │
│ "Jordan relies on rapport but loses on price"     │
│                                                   │
│ PRIMARY WEAKNESS    ROOT CAUSE                    │
│ Objection Handling  Lacks scripted pivot phrases  │
│                                                   │
│ NEXT DRILL                                        │
│ Assign: "Skeptical Homeowner" difficulty 3        │
│                                                   │
│ COACHING SCRIPT                                   │
│ "Jordan, when they say the price is too high..."  │
│                     [Copy to clipboard]           │
│                                                   │
│ EXPECTED OUTCOME                                  │
│ +1.2 points on Objection in 4-6 sessions          │
└─────────────────────────────────────────────────┘
```

- "Copy to clipboard" button copies `coaching_script` to clipboard with a ✓ confirmation flash
- "Assign Drill" button next to "NEXT DRILL" opens `AssignmentCreatePage` pre-filled with the recommended scenario type

**Implementation:**
- Fetch on page load alongside `fetchRepProgress`
- Use `Promise.allSettled` so insight failure doesn't block the rest of the page from rendering
- Store insight in local state, not global store

---

## Part 5: Frontend — ManagerReplayPage Turn Annotations

Enhance `dashboard/src/pages/ManagerReplayPage.tsx` with AI turn annotations.

**Design:**
- Add a collapsible "AI Coaching Notes" panel at the top of the transcript view
- When collapsed: shows a single line "5 coaching moments identified — 2 strengths, 3 weaknesses"
- When expanded: renders each annotation as a callout card ordered by turn position

**Annotation card:**
```
┌─── [STRENGTH] Turn 4 ─────────────────────────┐
│ ✓ Strong rapport opener                        │
│ The rep immediately acknowledged the homeowner  │
│ was busy, which built trust quickly.            │
└────────────────────────────────────────────────┘

┌─── [WEAKNESS] Turn 12 ────────────────────────┐
│ ✗ Buckled on price objection                   │
│ The rep said "I understand if the price is a   │
│ concern" which validates the objection instead  │
│ of pivoting.                                    │
│ 💡 Try: "Most of our customers felt the same   │
│ way until they saw how much they saved year 1." │
└────────────────────────────────────────────────┘
```

- Strength cards: left border `#2D5A3D`, background `rgba(45, 90, 61, 0.06)`
- Weakness cards: left border `#dc2626`, background `rgba(220, 38, 38, 0.06)`
- Clicking an annotation card scrolls the transcript to that turn and highlights it
- "Jump to turn" link on each card

**Implementation:**
- Call `fetchSessionAnnotations` on page load alongside `fetchReplay`
- Use `Promise.allSettled` — annotation failure should not break replay
- Highlight a transcript turn by adding a `ring-2 ring-accent` class to the turn row when its `turn_id` matches the selected annotation

---

## Part 6: Frontend — CoachingLabPage AI Summary Banner

Add a 3-sentence AI summary at the top of `CoachingLabPage.tsx`.

**Design:**
- Full-width glassmorphism banner at the top of the page, above all KPI cards
- Content: Claude-generated paragraph summarizing the team's coaching patterns for the period
- Example: "Your team's biggest coaching gap is objection handling — 4 of 6 reps show weakness tags in this category. Coaching interventions on Jordan and Marcus led to the strongest uplift (+1.8 pts) when notes were marked visible to rep. Focus this week: assign a targeted retry to the 3 reps with calibration_drift > 0.5."
- "Regenerate" button refreshes the summary

**Implementation:**
- Add a new backend endpoint `POST /manager/ai/team-coaching-summary` that accepts `manager_id` + `period_days`, queries `CoachingAnalyticsResponse` data, and calls Claude to generate a 3-sentence team summary
- Frontend: fetch on page load, show skeleton while loading, full text when ready

---

## Acceptance Criteria

- [ ] `POST /manager/ai/rep-insight` returns valid `RepInsightResponse`, caches in Redis
- [ ] `POST /manager/ai/session-annotations` returns valid `SessionAnnotationsResponse`, caches in Redis
- [ ] `POST /manager/ai/team-coaching-summary` returns a 3-sentence coaching summary
- [ ] RepProgressPage renders AI Insight panel with all 6 fields
- [ ] "Copy coaching script" copies to clipboard correctly
- [ ] ManagerReplayPage renders AI annotations panel, collapsible, jump-to-turn works
- [ ] CoachingLabPage renders team summary banner
- [ ] All 3 endpoints gracefully return errors if Claude API is unavailable (don't crash the page)
- [ ] Redis caching works — second call for same rep/session returns instantly
- [ ] No TypeScript errors, no `any` types added
