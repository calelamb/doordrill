# PHASE M1 — Animated Visualization Suite
# Goal: Make DoorDrill Manager's charts jaw-dropping. Every graph should animate on mount,
# respond to data updates, and communicate insight at a glance.

---

## Files to read first (required before touching anything)

- `dashboard/src/lib/types.ts` — all data shapes, especially `CommandCenterResponse`, `RepProgress`, `CoachingAnalyticsResponse`, `ScenarioIntelligenceResponse`
- `dashboard/src/lib/api.ts` — all fetch functions
- `dashboard/src/components/EChartSurface.tsx` — the ECharts wrapper pattern
- `dashboard/src/pages/AnalyticsPage.tsx` — current analytics implementation
- `dashboard/src/pages/RepProgressPage.tsx` — current rep drill-down
- `dashboard/src/styles/global.css` — design token reference

---

## Deliverable 1: Team Skill Heatmap (AnalyticsPage.tsx)

Replace the existing "weakest categories" list with a full team skill heatmap grid.

**Design:**
- Rows = reps (from `rep_risk_matrix` — already in `CommandCenterResponse`)
- Columns = grading categories: Opening, Pitch, Objection Handling, Closing, Professionalism
- Cell value = average score for that rep × category (derive from `RepProgress.current_period_category_averages`)
- Cell color: interpolate across `#dc2626` (red, score ≤ 5.0) → `#f59e0b` (amber, 6.5) → `#2D5A3D` (forest green, ≥ 8.5)
- On hover: tooltip showing exact score + "3 sessions below benchmark"
- On cell click: navigate to `/manager/reps/:repId/progress` with the category pre-selected

**Implementation:**
- Use Apache ECharts HeatMap series via `EChartSurface`
- Animate cells on mount with `animationDuration: 800`, `animationEasing: 'cubicOut'`
- Data fetching: call `fetchRepProgress` for each rep in the risk matrix (parallel with `Promise.all`)
- Add a loading skeleton that matches the grid dimensions
- Place this component in a new file: `dashboard/src/components/TeamSkillHeatmap.tsx`
- Export and use it in `AnalyticsPage.tsx` replacing the weakest categories section

---

## Deliverable 2: Animated Score Trend Line (AnalyticsPage.tsx)

The existing score trend chart needs major upgrades.

**Enhancements:**
- Add a benchmark band rendered as a shaded area between the 25th and 75th percentile lines (data from `BenchmarksResponse.score_benchmarks`)
- Animate the line drawing from left to right on mount using ECharts `animationDuration: 1200`
- Add a gradient fill under the team trend line: `#2D5A3D` at 40% opacity fading to transparent
- Add period comparison: show previous period trend as a dashed line in muted gray
- Show a "momentum indicator" badge in the top-right corner of the chart: up arrow (green) if `team_average_delta_vs_previous_period > 0`, down arrow (red) if negative, with the delta value
- Crosshair tooltip showing: date, session count, average score, delta vs previous period

**Implementation:**
- Use ECharts line series with `smooth: true`, `areaStyle` with gradient
- Call `fetchManagerBenchmarks` alongside `fetchManagerCommandCenter`
- Update the component in `AnalyticsPage.tsx` — do not create a separate file for this one

---

## Deliverable 3: Animated Radar Chart (RepProgressPage.tsx)

The existing category radar chart should be significantly enhanced.

**Enhancements:**
- Show TWO radar series simultaneously: current period (solid forest green fill) + previous period (dashed amber outline, no fill)
- Animate on mount: radar fills in with a radial sweep animation (`animationDuration: 1000`, `animationEasing: 'elasticOut'`)
- On period switch (7/30/90 day selector), animate the transition between states using ECharts `setOption` with `notMerge: false`
- Indicator labels show category name + benchmark score: "Objection (avg: 6.8)"
- Add a "Biggest Gap" callout below the chart: a single highlighted chip showing the category with the largest negative delta vs. benchmark

**Implementation:**
- Build `dashboard/src/components/RepRadarChart.tsx` using EChartSurface
- Accept props: `current: Record<string, number>`, `previous: Record<string, number>`, `benchmarks: Record<string, number>`
- Use in `RepProgressPage.tsx`

---

## Deliverable 4: Score Distribution Histogram (AnalyticsPage.tsx)

The existing histogram needs to feel alive and informative.

**Enhancements:**
- Bars animate upward on mount with staggered delay (bar 0: 0ms, bar 1: 80ms, bar 2: 160ms, etc.)
- Color each bar based on score range: below 6.0 = red tint, 6.0–7.5 = amber tint, above 7.5 = forest green
- Overlay a bell curve / normal distribution line in dashed gray to show the shape vs. "ideal" distribution
- On hover: tooltip shows "12 sessions scored 7.0–7.5 — 23% of total"
- Below the chart: three KPI chips: "X reps at risk (< 6.0)", "X reps on target (6.0–7.5)", "X reps exceeding (> 7.5)"

**Implementation:**
- Enhance the existing histogram section in `AnalyticsPage.tsx` using EChartSurface bar series
- KPI chips use the shared `ScoreChip` component from `components/shared/ScoreChip.tsx`

---

## Deliverable 5: Rep Risk Quadrant Scatter Plot (AnalyticsPage.tsx)

Replace or upgrade the existing rep risk matrix display with a proper quadrant scatter.

**Design:**
- X-axis: `score_delta` (trend — negative = declining, positive = improving)
- Y-axis: `average_score` (absolute performance)
- Bubble size: `volatility` (higher = larger bubble)
- Bubble color: `risk_level` — "high" = `#dc2626`, "medium" = `#f59e0b`, "low" = `#2D5A3D`
- Quadrant dividers: dashed lines at x=0 and y=7.0 (the passing threshold)
- Quadrant labels in each corner: "Rising Stars" (top right), "At Risk" (top left with declining), "Struggling" (bottom left), "Plateaued" (bottom right — high score but stagnant)
- On bubble hover: tooltip with rep name, score, delta, risk level, "View Rep →" link
- On bubble click: navigate to `/manager/reps/:repId/progress`

**Implementation:**
- Use ECharts scatter series via EChartSurface
- Data from `CommandCenterResponse.rep_risk_matrix` — already typed and fetched
- Animate bubbles on mount: scatter with `animationDuration: 600`, `animationDelay` staggered by index
- Build as `dashboard/src/components/RepRiskQuadrant.tsx`, use in `AnalyticsPage.tsx`

---

## Deliverable 6: Objection Failure Cluster Chart (ScenarioIntelligencePage.tsx)

Enhance the existing objection failure map into a treemap-style visualization.

**Design:**
- Use ECharts TreeMap series
- Each node: a specific objection tag (e.g., "price too high", "not interested", "already have service")
- Node size = frequency count (`objection_failure_map` from `ScenarioIntelligenceResponse`)
- Node color = failure severity: red if failure rate > 60%, amber 40–60%, green < 40%
- On click: filter the scenario leaderboard below to show only scenarios where this objection appears
- Animate on mount with ECharts built-in treemap animation

**Implementation:**
- Build `dashboard/src/components/ObjectionTreemap.tsx`
- Data from `fetchManagerScenarioIntelligence` which returns `ScenarioIntelligenceResponse` including `objection_failure_map`
- Use in `ScenarioIntelligencePage.tsx` replacing the existing bar chart

---

## Framer Motion Page Transitions

Add staggered entry animations to all page containers.

In each page component, wrap the top-level div with:
```tsx
import { motion } from "framer-motion";

const pageVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { staggerChildren: 0.08, duration: 0.4, ease: "easeOut" }
  }
};

const cardVariants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0 }
};
```

Wrap each stat card and chart section as `<motion.div variants={cardVariants}>`.

Apply to: `AnalyticsPage.tsx`, `RepProgressPage.tsx`, `CoachingLabPage.tsx`, `ScenarioIntelligencePage.tsx`

---

## Loading Skeletons

Every chart section must have a skeleton while data loads. Pattern:

```tsx
if (loading) return (
  <div className="animate-pulse bg-white/30 backdrop-blur-md rounded-2xl h-64 w-full" />
);
```

For the heatmap specifically, render a grid of `rows × 5` skeleton cells sized to match the real chart.

---

## Acceptance Criteria

- [ ] TeamSkillHeatmap renders all reps × 5 categories with correct color interpolation
- [ ] Score trend line animates on mount and shows benchmark band
- [ ] RepRadarChart shows current + previous period with animated transition
- [ ] Score distribution histogram bars animate in staggered sequence
- [ ] Rep Risk Quadrant renders all reps as bubbles in correct quadrants
- [ ] Objection treemap renders and filters scenario table on click
- [ ] All pages have Framer Motion staggered entry
- [ ] All charts have loading skeleton states
- [ ] No TypeScript errors, no `any` types
- [ ] All chart interactions (hover tooltips, click navigation) work correctly
