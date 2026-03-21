import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, animate, motion } from "framer-motion";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangle,
  ArrowRight,
  ShieldAlert,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ChartSkeleton } from "../components/shared/ChartSkeleton";
import { DataTable } from "../components/shared/DataTable";
import { EmptyState } from "../components/shared/EmptyState";
import { ScoreTrajectoryBar } from "../components/shared/ScoreTrajectoryBar";
import { AiMetaStrip } from "../components/shared/AiMetaStrip";
import { buildAssignmentPrefillState } from "../lib/assignmentPrefill";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchRepInsight, fetchRepRiskDetail } from "../lib/api";
import { getCategoryLabel, normalizeCategoryKey } from "../lib/analytics";
import { cardVariants, pageVariants } from "../lib/motion";
import type { RepInsightResponse, RepRiskDetail, RepRiskDetailResponse } from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "14", label: "14 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];

type VulnerabilityRow = {
  repId: string;
  repName: string;
  categoryKey: string;
  repAverage: number | null;
  teamAverage: number | null;
  gap: number;
};

const columnHelper = createColumnHelper<VulnerabilityRow>();

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number") {
    return "--";
  }
  return value.toFixed(1);
}

function formatSlope(value: number | null | undefined): string {
  if (typeof value !== "number") {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}/session`;
}

function volatilityLabel(value: number): string {
  if (value < 0.45) {
    return "low";
  }
  if (value < 1.1) {
    return "moderate";
  }
  return "high";
}

function riskTone(level: RepRiskDetail["risk_level"]): string {
  if (level === "high") {
    return "border-red-200 bg-red-50/80 text-red-700";
  }
  if (level === "medium") {
    return "border-amber-200 bg-amber-50/80 text-amber-800";
  }
  return "border-emerald-200 bg-emerald-50/80 text-emerald-700";
}

function summarizeHighRiskRep(rep: RepRiskDetail): string {
  const firstName = rep.rep_name.split(" ")[0] ?? rep.rep_name;
  if (rep.decline_detected) {
    return `${firstName} is declining`;
  }
  if (rep.stall_detected && rep.days_since_last_session !== null) {
    return `${firstName} hasn't drilled in ${rep.days_since_last_session} days`;
  }
  if (rep.plateau_detected) {
    return `${firstName} is plateaued`;
  }
  return `${firstName} needs attention`;
}

function AnimatedCount({ value }: { value: number }) {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    const controls = animate(0, value, {
      duration: 0.7,
      ease: "easeOut",
      onUpdate: (latest) => setDisplayValue(Math.round(latest)),
    });
    return () => controls.stop();
  }, [value]);

  return <span>{displayValue}</span>;
}

function RiskIntelligenceSkeleton() {
  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.div variants={cardVariants} className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-3">
          <ChartSkeleton heightClass="h-6" className="max-w-[180px]" />
          <ChartSkeleton heightClass="h-10" className="max-w-[300px]" />
          <ChartSkeleton heightClass="h-4" className="max-w-[500px]" />
        </div>
        <ChartSkeleton heightClass="h-12" className="w-full max-w-[260px]" />
      </motion.div>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <ChartSkeleton key={index} heightClass="h-32" className="rounded-[28px]" />
        ))}
      </motion.section>

      <motion.section variants={cardVariants} className="space-y-4">
        {Array.from({ length: 3 }).map((_, index) => (
          <ChartSkeleton key={index} heightClass="h-[280px]" className="rounded-[32px]" />
        ))}
      </motion.section>
    </motion.main>
  );
}

type RepInsightDrawerProps = {
  managerId: string;
  period: PeriodKey;
  rep: RepRiskDetail | null;
  onClose: () => void;
};

function RepInsightDrawer({ managerId, period, rep, onClose }: RepInsightDrawerProps) {
  const navigate = useNavigate();
  const [insight, setInsight] = useState<RepInsightResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!rep) {
      return;
    }

    let cancelled = false;
    const repId = rep.rep_id;

    async function loadInsight() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetchRepInsight(managerId, repId, Number(period));
        if (!cancelled) {
          setInsight(response);
        }
      } catch (loadError) {
        if (isAuthError(loadError)) {
          clearStoredAuth();
          navigate("/login", { replace: true });
          return;
        }
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Could not load AI coach insight.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadInsight();

    return () => {
      cancelled = true;
    };
  }, [managerId, navigate, period, rep]);

  return (
    <AnimatePresence>
      {rep ? (
        <motion.div
          className="fixed inset-0 z-50 flex justify-end bg-ink/25 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.aside
            className="flex h-full w-full max-w-xl flex-col border-l border-white/20 bg-background/95 p-6 shadow-2xl"
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 40, opacity: 0 }}
            transition={{ type: "spring", stiffness: 210, damping: 24 }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-white/30 pb-5">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">AI Coach Insight</div>
                <h2 className="mt-2 text-2xl font-black tracking-tight text-ink">{rep.rep_name}</h2>
                <p className="mt-2 text-sm text-muted">Targeted coaching analysis for the last {period} days.</p>
              </div>
              <button
                type="button"
                aria-label="Close AI coach insight panel"
                onClick={onClose}
                className="rounded-full border border-white/35 bg-white/70 px-3 py-1.5 text-sm font-medium text-ink transition hover:bg-white"
              >
                Close
              </button>
            </div>

            <div className="mt-6 flex-1 space-y-5 overflow-y-auto pr-1">
              {loading && !insight ? (
                <div className="space-y-4">
                  <ChartSkeleton heightClass="h-6" className="max-w-[180px]" />
                  <ChartSkeleton heightClass="h-20" className="rounded-2xl" />
                  <ChartSkeleton heightClass="h-20" className="rounded-2xl" />
                  <ChartSkeleton heightClass="h-24" className="rounded-2xl" />
                </div>
              ) : null}

              {!loading && !insight && error ? (
                <div className="rounded-3xl border border-red-200 bg-red-50/80 p-5 text-sm text-red-700">{error}</div>
              ) : null}

              {insight ? (
                <>
                  {loading ? (
                    <div className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900">
                      Refreshing AI coach insight...
                    </div>
                  ) : null}

                  {!loading && error ? (
                    <div className="rounded-2xl border border-red-200 bg-red-50/80 px-4 py-3 text-sm text-red-700">
                      {error}
                    </div>
                  ) : null}

                  <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Diagnosis</div>
                    <p className="mt-3 text-2xl font-black tracking-tight text-ink">{insight.headline}</p>
                    <AiMetaStrip meta={insight.ai_meta} />
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Primary Weakness</div>
                      <p className="mt-3 text-base font-semibold text-ink">{insight.primary_weakness}</p>
                    </div>
                    <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Expected Outcome</div>
                      <p className="mt-3 text-sm leading-6 text-ink">{insight.expected_improvement}</p>
                    </div>
                  </div>

                  <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Root Cause</div>
                    <p className="mt-3 text-sm leading-6 text-ink">{insight.root_cause}</p>
                  </div>

                  <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Recommended Drill</div>
                    <p className="mt-3 text-sm leading-6 text-ink">{insight.drill_recommendation}</p>
                    <button
                      type="button"
                      aria-label={`Assign recommended drill for ${rep.rep_name}`}
                      onClick={() =>
                        navigate("/manager/assignments/new", {
                          state: buildAssignmentPrefillState(insight.assignment_suggestion, {
                            prefillRepIds: [rep.rep_id],
                            prefillScenarioSearch: insight.assignment_suggestion?.scenario_search ?? insight.drill_recommendation,
                          }),
                        })
                      }
                      className="mt-4 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover"
                    >
                      Assign Drill
                    </button>
                  </div>

                  <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Coaching Script</div>
                    <p className="mt-3 text-sm leading-6 text-ink">{insight.coaching_script}</p>
                  </div>
                </>
              ) : null}
            </div>
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

export function RiskIntelligencePage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<PeriodKey>("30");
  const [data, setData] = useState<RepRiskDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedInsightRep, setSelectedInsightRep] = useState<RepRiskDetail | null>(null);
  const repListRef = useRef<HTMLElement | null>(null);

  const loadData = useCallback(async () => {
    if (!managerId) {
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetchRepRiskDetail(managerId, { period });
      setData(response);
    } catch (loadError) {
      if (isAuthError(loadError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(loadError instanceof Error ? loadError.message : "Failed to load risk intelligence.");
    } finally {
      setLoading(false);
    }
  }, [managerId, navigate, period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const reps = useMemo(
    () => [...(data?.reps ?? [])].sort((left, right) => right.risk_score - left.risk_score),
    [data?.reps]
  );

  const highRiskReps = useMemo(() => reps.filter((rep) => rep.risk_level === "high"), [reps]);

  const summaryAlert = useMemo(() => {
    if (!highRiskReps.length) {
      return null;
    }
    return [summarizeHighRiskRep(highRiskReps[0]), highRiskReps[1] ? summarizeHighRiskRep(highRiskReps[1]) : null]
      .filter(Boolean)
      .join(", ");
  }, [highRiskReps]);

  const counts = useMemo(
    () => ({
      highRisk: reps.filter((rep) => rep.risk_level === "high").length,
      plateaued: reps.filter((rep) => rep.plateau_detected).length,
      declining: reps.filter((rep) => rep.decline_detected).length,
      rising: reps.filter((rep) => rep.breakthrough_detected).length,
    }),
    [reps]
  );

  const vulnerabilityRows = useMemo<VulnerabilityRow[]>(() => {
    if (!data) {
      return [];
    }

    return reps
      .filter(
        (rep) =>
          !!rep.most_vulnerable_category &&
          typeof rep.category_gap_vs_team === "number" &&
          rep.category_gap_vs_team > 0
      )
      .map((rep) => {
        const categoryKey = normalizeCategoryKey(rep.most_vulnerable_category) ?? rep.most_vulnerable_category ?? "";
        const teamAverage = data.team_category_averages[categoryKey] ?? null;
        const repAverage =
          teamAverage !== null && typeof rep.category_gap_vs_team === "number"
            ? Number(Math.max(0, teamAverage - rep.category_gap_vs_team).toFixed(2))
            : null;
        return {
          repId: rep.rep_id,
          repName: rep.rep_name,
          categoryKey,
          repAverage,
          teamAverage,
          gap: rep.category_gap_vs_team ?? 0,
        };
      })
      .sort((left, right) => right.gap - left.gap);
  }, [data, reps]);

  const vulnerabilityColumns = useMemo(
    () =>
      [
      columnHelper.accessor("repName", {
        header: "Rep",
        cell: (info) => <span className="font-semibold text-ink">{info.getValue()}</span>,
      }),
      columnHelper.accessor("categoryKey", {
        header: "Category",
        cell: (info) => {
          const normalizedKey = normalizeCategoryKey(info.getValue());
          return <span>{normalizedKey ? getCategoryLabel(normalizedKey) : info.getValue()}</span>;
        },
      }),
      columnHelper.accessor("repAverage", {
        header: "Rep Avg",
        cell: (info) => formatScore(info.getValue()),
      }),
      columnHelper.accessor("teamAverage", {
        header: "Team Avg",
        cell: (info) => formatScore(info.getValue()),
      }),
      columnHelper.accessor("gap", {
        header: "Gap",
        cell: (info) => <span className="font-semibold text-red-700">-{info.getValue().toFixed(1)}</span>,
      }),
      columnHelper.display({
        id: "action",
        header: "Action",
        cell: ({ row }) => (
          <button
            type="button"
            aria-label={`Assign drill for ${row.original.repName}`}
            onClick={() => {
              const params = new URLSearchParams({ repId: row.original.repId, category: row.original.categoryKey });
              navigate(`/manager/assignments/new?${params.toString()}`, {
                state: {
                  prefillRepIds: [row.original.repId],
                  prefillCategoryKey: row.original.categoryKey,
                  prefillScenarioSearch: getCategoryLabel(normalizeCategoryKey(row.original.categoryKey) ?? "opening"),
                },
              });
            }}
            className="rounded-full border border-white/35 bg-white/70 px-3 py-1.5 text-xs font-semibold text-ink transition hover:bg-white"
          >
            Assign
          </button>
          ),
      }),
      ] as ColumnDef<VulnerabilityRow, unknown>[],
    [navigate]
  );

  if (loading) {
    return <RiskIntelligenceSkeleton />;
  }

  if (error) {
    return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  }

  if (!data) {
    return <EmptyState variant="empty" message="No risk intelligence is available yet." icon={ShieldAlert} />;
  }

  return (
    <>
      <motion.main
        className="mx-auto max-w-7xl space-y-6 px-6 py-6"
        initial="hidden"
        animate="visible"
        variants={pageVariants}
      >
        <motion.header variants={cardVariants} className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Manager Analytics</div>
            <h1 className="mt-2 text-3xl font-black tracking-tight text-ink">Risk Intelligence</h1>
            <p className="mt-2 max-w-3xl text-sm text-muted">
              Surface plateau, decline, stall, and breakthrough signals before they turn into team retention problems.
            </p>
          </div>

          <div className="flex rounded-2xl border border-white/35 bg-white/55 p-1">
            {PERIOD_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                aria-label={`Show rep risk detail for the last ${option.label}`}
                onClick={() => setPeriod(option.key)}
                className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
                  period === option.key ? "bg-accent text-white" : "text-muted hover:bg-white/70 hover:text-ink"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </motion.header>

        {highRiskReps.length ? (
          <motion.section
            variants={cardVariants}
            className="rounded-[28px] border border-red-200 bg-red-50/80 p-5 shadow-sm"
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-full bg-red-600/10 p-2 text-red-600">
                  <AlertTriangle className="h-5 w-5" />
                </div>
                <div className="border-l-[3px] border-red-600 pl-4">
                  <p className="text-base font-semibold text-red-800">
                    {highRiskReps.length} rep{highRiskReps.length === 1 ? "" : "s"} need immediate attention
                  </p>
                  <p className="mt-1 text-sm text-red-700">{summaryAlert}</p>
                </div>
              </div>
              <button
                type="button"
                aria-label="Scroll to rep risk cards"
                onClick={() => repListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
                className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-white/70 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-white"
              >
                View Details
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </motion.section>
        ) : null}

        <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[
            { label: "At Risk", count: counts.highRisk, tone: "text-red-700", accent: "bg-red-600/10" },
            { label: "Plateaued", count: counts.plateaued, tone: "text-amber-700", accent: "bg-amber-500/10" },
            { label: "Declining", count: counts.declining, tone: "text-red-700", accent: "bg-red-600/10" },
            { label: "Rising Stars", count: counts.rising, tone: "text-emerald-700", accent: "bg-emerald-600/10" },
          ].map((card) => (
            <div
              key={card.label}
              className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl"
            >
              <div className={`inline-flex rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${card.accent} ${card.tone}`}>
                {card.label}
              </div>
              <div className={`mt-5 text-4xl font-black tracking-tight ${card.tone}`}>
                <AnimatedCount value={card.count} />
              </div>
            </div>
          ))}
        </motion.section>

        <motion.section ref={repListRef} variants={cardVariants} className="space-y-4">
          {reps.length ? (
            reps.map((rep, index) => {
              const categoryKey = normalizeCategoryKey(rep.most_vulnerable_category);
              const vulnerabilityLabel = categoryKey ? getCategoryLabel(categoryKey) : null;
              const projectedBelowPassing =
                typeof rep.projected_score_10_sessions === "number" && rep.projected_score_10_sessions < 6;
              const statusFlags = [
                rep.decline_detected
                  ? {
                      tone: "text-red-700",
                      label: `Declining — ${formatSlope(rep.score_trend_slope)} over the last 10 sessions`,
                    }
                  : null,
                rep.plateau_detected
                  ? {
                      tone: "text-amber-700",
                      label: `Plateaued — score locked around ${formatScore(rep.current_avg_score)} for the last ${Math.min(8, rep.session_count || 8)} sessions`,
                    }
                  : null,
                rep.stall_detected && rep.days_since_last_session !== null
                  ? {
                      tone: "text-slate-700",
                      label: `Stalled — no drill in ${rep.days_since_last_session} days`,
                    }
                  : null,
                rep.breakthrough_detected
                  ? {
                      tone: "text-emerald-700",
                      label: "Rising — on track for top performer status",
                    }
                  : null,
              ].filter(Boolean) as Array<{ tone: string; label: string }>;

              if (vulnerabilityLabel && typeof rep.category_gap_vs_team === "number") {
                statusFlags.push({
                  tone: "text-amber-700",
                  label: `Weakest: ${vulnerabilityLabel} (${rep.category_gap_vs_team.toFixed(1)} below team avg)`,
                });
              }

              return (
                <motion.article
                  key={rep.rep_id}
                  variants={cardVariants}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: index * 0.04 }}
                  className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center gap-3">
                        <h2 className="text-2xl font-black tracking-tight text-ink">{rep.rep_name}</h2>
                        <span className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${riskTone(rep.risk_level)}`}>
                          {rep.risk_level} risk
                        </span>
                        <span className="text-sm font-semibold text-ink">{Math.round(rep.risk_score)} risk</span>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted">
                        <span className="font-medium text-ink">Avg Score: {formatScore(rep.current_avg_score)}</span>
                        <span className={`inline-flex items-center gap-1.5 ${rep.score_trend_slope !== null && rep.score_trend_slope < 0 ? "text-red-700" : "text-emerald-700"}`}>
                          {rep.score_trend_slope !== null && rep.score_trend_slope < 0 ? (
                            <TrendingDown className="h-4 w-4" />
                          ) : (
                            <TrendingUp className="h-4 w-4" />
                          )}
                          {formatSlope(rep.score_trend_slope)}
                        </span>
                        <span>{rep.session_count} sessions</span>
                        <span className="capitalize">Volatility: {volatilityLabel(rep.score_volatility)}</span>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-white/35 bg-white/55 px-4 py-3 text-right">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Red Flags</div>
                      <div className="mt-2 text-2xl font-black tracking-tight text-ink">{rep.red_flag_count}</div>
                    </div>
                  </div>

                  <div className="mt-5 space-y-2">
                    {statusFlags.length ? (
                      statusFlags.map((flag) => (
                        <div key={flag.label} className={`text-sm font-medium ${flag.tone}`}>
                          {flag.label}
                        </div>
                      ))
                    ) : (
                      <div className="text-sm font-medium text-muted">Stable trend with no immediate risk flags.</div>
                    )}
                  </div>

                  <div className="mt-6 rounded-[28px] border border-white/25 bg-white/45 p-5">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Trajectory</div>
                    <div className="mt-4">
                      <ScoreTrajectoryBar
                        currentScore={rep.current_avg_score}
                        projectedScore={rep.projected_score_10_sessions}
                        size="md"
                      />
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-muted">
                      <span>
                        Projected:{" "}
                        <span className={`font-semibold ${projectedBelowPassing ? "text-red-700" : "text-ink"}`}>
                          {formatScore(rep.projected_score_10_sessions)}
                        </span>{" "}
                        in 10 sessions
                      </span>
                      {typeof rep.current_avg_score === "number" && typeof rep.projected_score_10_sessions === "number" ? (
                        <span>
                          Current {formatScore(rep.current_avg_score)} → {formatScore(rep.projected_score_10_sessions)} if trend continues
                        </span>
                      ) : (
                        <span>Projection becomes available after at least two scored sessions.</span>
                      )}
                    </div>
                  </div>

                  <div className="mt-6 flex flex-wrap gap-3">
                    <button
                      type="button"
                      aria-label={`View ${rep.rep_name} progress`}
                      onClick={() => navigate(`/manager/reps/${rep.rep_id}/progress`)}
                      className="rounded-xl border border-white/35 bg-white/70 px-4 py-2.5 text-sm font-semibold text-ink transition hover:bg-white"
                    >
                      View Rep
                    </button>
                    <button
                      type="button"
                      aria-label={`Assign drill for ${rep.rep_name}`}
                      onClick={() => {
                        const params = new URLSearchParams({ repId: rep.rep_id });
                        if (categoryKey) {
                          params.set("category", categoryKey);
                        }
                        navigate(`/manager/assignments/new?${params.toString()}`, {
                          state: {
                            prefillRepIds: [rep.rep_id],
                            prefillCategoryKey: categoryKey ?? undefined,
                            prefillScenarioSearch: vulnerabilityLabel ?? undefined,
                          },
                        });
                      }}
                      className="rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-hover"
                    >
                      Assign Drill
                    </button>
                    <button
                      type="button"
                      aria-label={`Open AI coach insight for ${rep.rep_name}`}
                      onClick={() => setSelectedInsightRep(rep)}
                      className="inline-flex items-center gap-2 rounded-xl border border-white/35 bg-white/70 px-4 py-2.5 text-sm font-semibold text-ink transition hover:bg-white"
                    >
                      <Sparkles className="h-4 w-4 text-accent" />
                      AI Coach Insight
                    </button>
                  </div>
                </motion.article>
              );
            })
          ) : (
            <div className="rounded-[32px] border border-white/30 bg-white/40 px-6 py-12 shadow-xl shadow-black/5 backdrop-blur-2xl">
              <EmptyState variant="empty" message="No reps are available for risk analysis yet." icon={ShieldAlert} />
            </div>
          )}
        </motion.section>

        <motion.section
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Category Vulnerability</div>
            <h2 className="mt-2 text-xl font-black tracking-tight text-ink">Where reps lag the team baseline</h2>
          </div>
          <DataTable
            columns={vulnerabilityColumns}
            data={vulnerabilityRows}
            emptyMessage="No category vulnerabilities are currently below the team baseline."
          />
        </motion.section>
      </motion.main>

      <RepInsightDrawer
        managerId={managerId}
        period={period}
        rep={selectedInsightRep}
        onClose={() => setSelectedInsightRep(null)}
      />
    </>
  );
}
