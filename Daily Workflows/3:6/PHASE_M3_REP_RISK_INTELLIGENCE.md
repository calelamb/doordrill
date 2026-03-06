# PHASE M3 — Rep Risk Intelligence
# Goal: Surface performance risk before it becomes a retention problem.
# Managers should know exactly which reps are plateauing, declining, or about
# to quit — before it shows up in field results.

---

## Files to read first (required before touching anything)

- `dashboard/src/lib/types.ts` — `CommandCenterResponse.rep_risk_matrix`, `RepProgress`
- `dashboard/src/lib/api.ts` — `fetchManagerCommandCenter`, `fetchRepProgress`
- `dashboard/src/pages/AnalyticsPage.tsx` — where the risk matrix currently lives
- `dashboard/src/pages/RepProgressPage.tsx` — individual rep view
- `backend/app/routers/manager.py` — add new analytics endpoint here

---

## Part 1: Backend — Enhanced Risk Analytics Endpoint

### New endpoint: GET /manager/analytics/rep-risk-detail

Add to `backend/app/routers/manager.py`.

**Query parameters:** `manager_id`, `period` (days, default 30)

**Logic per rep (for all reps under this manager):**

1. **Plateau detection** — if the standard deviation of the last 8 session scores is < 0.4 AND the rep has ≥ 8 sessions, flag as "plateaued"
2. **Decline detection** — compute linear regression slope of last 10 session scores. If slope < -0.15 per session, flag as "declining"
3. **Breakthrough detection** — if slope > +0.2 per session AND average_score > 7.5, flag as "rising"
4. **Stall detection** — if the rep has 0 sessions in the last 14 days but has had sessions before, flag as "stalled"
5. **Trajectory projection** — project the rep's score in 10 sessions using the current slope (clamped to 0–10)
6. **Category vulnerability** — identify the single category where the rep is furthest below the team average

**Response schema:**
```python
class RepRiskDetail(BaseModel):
    rep_id: str
    rep_name: str
    current_avg_score: float | None
    score_trend_slope: float | None  # per-session change
    score_volatility: float  # std deviation
    projected_score_10_sessions: float | None
    plateau_detected: bool
    decline_detected: bool
    breakthrough_detected: bool
    stall_detected: bool
    days_since_last_session: int | None
    most_vulnerable_category: str | None
    category_gap_vs_team: float | None  # how far below team avg in that category
    risk_level: Literal["high", "medium", "low"]
    risk_score: float  # 0–100
    session_count: int
    red_flag_count: int

class RepRiskDetailResponse(BaseModel):
    manager_id: str
    period: str
    generated_at: str
    reps: List[RepRiskDetail]
    team_avg_score: float | None
    team_category_averages: Dict[str, float]
```

---

## Part 2: Frontend — Types

Add to `dashboard/src/lib/types.ts`:

```typescript
export type RepRiskDetail = {
  rep_id: string;
  rep_name: string;
  current_avg_score: number | null;
  score_trend_slope: number | null;
  score_volatility: number;
  projected_score_10_sessions: number | null;
  plateau_detected: boolean;
  decline_detected: boolean;
  breakthrough_detected: boolean;
  stall_detected: boolean;
  days_since_last_session: number | null;
  most_vulnerable_category: string | null;
  category_gap_vs_team: number | null;
  risk_level: "high" | "medium" | "low";
  risk_score: number;
  session_count: number;
  red_flag_count: number;
};

export type RepRiskDetailResponse = {
  manager_id: string;
  period: string;
  generated_at: string;
  reps: RepRiskDetail[];
  team_avg_score: number | null;
  team_category_averages: Record<string, number>;
};
```

Add API function to `dashboard/src/lib/api.ts`:
```typescript
export async function fetchRepRiskDetail(
  managerId: string,
  options: { period?: string } = {}
): Promise<RepRiskDetailResponse> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  return requestJson<RepRiskDetailResponse>(
    `/manager/analytics/rep-risk-detail?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}
```

---

## Part 3: Frontend — Risk Intelligence Panel (new page section)

Create a new page: `dashboard/src/pages/RiskIntelligencePage.tsx`

Add route to `App.tsx`:
```tsx
<Route path="/manager/risk" element={<RiskIntelligencePage />} />
```

Add nav item to `Sidebar.tsx` between Analytics and Coaching Lab: "Risk Intelligence" with a shield icon.

---

### Section 1: Summary Alert Bar

Full-width alert at the top (only shown if any high-risk reps exist):

```
⚠ 2 reps need immediate attention — Jordan has been declining for 8 sessions,
  Marcus hasn't drilled in 18 days. [View Details ↓]
```

Background: `rgba(220, 38, 38, 0.08)`, border-left: 3px solid `#dc2626`
Clicking "View Details" smooth-scrolls to the rep card list below.

---

### Section 2: Status Cards Row

Four glassmorphism stat cards in a row:
- "At Risk" (count of `risk_level === "high"`) — red accent
- "Plateaued" (count with `plateau_detected`) — amber accent
- "Declining" (count with `decline_detected`) — red accent
- "Rising Stars" (count with `breakthrough_detected`) — green accent

Each card animates the count in with `framer-motion` counter animation on mount.

---

### Section 3: Rep Risk Cards (sorted by risk_score descending)

For each rep, render a glassmorphism card:

```
┌──────────────────────────────────────────────────────┐
│ Jordan M.                      [HIGH RISK]  8.2 risk │
│ Avg Score: 5.8  ↓ -0.18/session  📊 22 sessions     │
│                                                       │
│ 🔴 Declining for 8 sessions                          │
│ 🟡 Weakest: Objection Handling (2.1 below team avg)  │
│                                                       │
│ TRAJECTORY                                            │
│ ━━━━━━━━░░░░░░░░  Projected: 4.6 in 10 sessions      │
│ (current 5.8 → 4.6 if trend continues)               │
│                                                       │
│ [View Rep] [Assign Drill] [AI Coach Insight]         │
└──────────────────────────────────────────────────────┘
```

**Trajectory bar:**
- A horizontal progress-bar-style component
- Current position marked with a dot
- Projected position marked with an arrow, colored red if projecting below 6.0
- Animate the dot and arrow on mount with Framer Motion spring

**Status flags:**
- `plateau_detected` → 🟡 "Plateaued — score locked at X.X for Y sessions"
- `decline_detected` → 🔴 "Declining — {slope:+.2f}/session over last 10 sessions"
- `stall_detected` → ⚫ "Stalled — no drill in {days_since_last_session} days"
- `breakthrough_detected` → 🟢 "Rising — on track for top performer status"

**Buttons:**
- "View Rep" → `/manager/reps/:repId/progress`
- "Assign Drill" → `/manager/assignments/new?repId=:repId` (pre-fill rep)
- "AI Coach Insight" → opens a slide-over panel that fetches and renders `RepInsightResponse` from Phase M2's `/manager/ai/rep-insight` endpoint

---

### Section 4: Category Vulnerability Table

A compact table showing which reps are weakest in which categories, sorted by gap size:

| Rep | Category | Rep Avg | Team Avg | Gap | Action |
|-----|----------|---------|----------|-----|--------|
| Jordan | Objection | 4.2 | 6.3 | -2.1 | Assign |
| Sarah | Closing | 5.1 | 6.8 | -1.7 | Assign |

Clicking "Assign" opens AssignmentCreatePage pre-filled with the rep and a scenario targeting that weakness category.

Use `DataTable` from `components/shared/DataTable.tsx`.

---

## Part 4: RepProgressPage — Trajectory Widget

Add a trajectory widget to the existing `RepProgressPage.tsx` directly below the summary stat cards.

**Design:**
```
SCORE TRAJECTORY
━━━━━━━●━━━━━━░░░░  6.8 today → 7.4 projected (10 sessions)
Trend: +0.12/session | Volatility: low
```

If declining:
```
━━━━━━━━━━●░░ 5.8 today → 4.6 projected (10 sessions) ⚠
Trend: -0.18/session | Volatility: high
```

- The filled portion of the bar represents current score / 10
- The dashed portion projects the trajectory
- Animate the bar filling on mount using Framer Motion `width` transition

---

## Part 5: Manager Feed — Risk Badges on Rep Names

In `ManagerFeedPage.tsx` and `FeedList.tsx`, add a small badge next to the rep name if that rep is high risk.

- Query `fetchRepRiskDetail` once on page load, store risk levels in a `Map<repId, risk_level>`
- On each feed card, if `riskMap.get(item.rep_id) === "high"`, show a small red dot badge next to rep name: `●` with tooltip "At risk — view rep profile"

---

## Acceptance Criteria

- [ ] `GET /manager/analytics/rep-risk-detail` returns all 6 risk signals per rep
- [ ] Plateau, decline, stall, breakthrough detection logic is correct (not arbitrary)
- [ ] RiskIntelligencePage renders with all 4 sections
- [ ] Alert bar only appears when high-risk reps exist
- [ ] Trajectory widget shows correct projected score
- [ ] Category Vulnerability Table links correctly to assignment flow
- [ ] RepProgressPage trajectory widget animates on mount
- [ ] Feed page shows risk badges on high-risk reps
- [ ] All data is real (no hardcoded mock values)
- [ ] No TypeScript errors
