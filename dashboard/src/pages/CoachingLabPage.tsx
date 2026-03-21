import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, BookOpenText, ChevronDown, ChevronUp, MessageSquareQuote, RefreshCcw, Scale, Sparkles, TrendingUp } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartSkeleton } from "../components/shared/ChartSkeleton";
import { EmptyState } from "../components/shared/EmptyState";
import { AiMetaStrip } from "../components/shared/AiMetaStrip";
import { buildAssignmentPrefillState } from "../lib/assignmentPrefill";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerCoachingAnalytics, fetchTeamCoachingSummary, fetchWeeklyTeamBriefing } from "../lib/api";
import { cardVariants, pageVariants } from "../lib/motion";
import type { CoachingAnalyticsResponse, TeamCoachingSummaryResponse, WeeklyTeamBriefingResponse } from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "7", label: "7D" },
  { key: "30", label: "30D" },
  { key: "90", label: "90D" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatRelativeTime(timestamp?: string | null) {
  if (!timestamp) {
    return "just now";
  }
  const deltaMs = Date.now() - new Date(timestamp).getTime();
  if (!Number.isFinite(deltaMs) || deltaMs < 60_000) {
    return "just now";
  }
  const deltaMinutes = Math.round(deltaMs / 60_000);
  if (deltaMinutes < 60) {
    return `${deltaMinutes}m ago`;
  }
  const deltaHours = Math.round(deltaMinutes / 60);
  if (deltaHours < 24) {
    return `${deltaHours}h ago`;
  }
  return `${Math.round(deltaHours / 24)}d ago`;
}

function CoachingLabSkeleton() {
  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.div variants={cardVariants} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-2">
          <ChartSkeleton heightClass="h-10" className="max-w-[220px]" />
          <ChartSkeleton heightClass="h-4" className="max-w-[360px]" />
        </div>
        <ChartSkeleton heightClass="h-12" className="w-full max-w-[220px]" />
      </motion.div>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 8 }).map((_, index) => (
          <ChartSkeleton key={index} heightClass="h-28" className="rounded-[28px]" />
        ))}
      </motion.section>

      {Array.from({ length: 4 }).map((_, index) => (
        <motion.section key={index} variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
          <ChartSkeleton heightClass="h-[360px]" className="rounded-[32px]" />
          <ChartSkeleton heightClass="h-[360px]" className="rounded-[32px]" />
        </motion.section>
      ))}
    </motion.main>
  );
}

function WeeklyBriefingSkeleton() {
  return (
    <div className="space-y-4">
      <ChartSkeleton heightClass="h-5" className="max-w-[220px]" />
      <ChartSkeleton heightClass="h-16" className="rounded-[28px]" />
      <div className="grid gap-4 md:grid-cols-[1.2fr_0.8fr]">
        <ChartSkeleton heightClass="h-40" className="rounded-[28px]" />
        <ChartSkeleton heightClass="h-40" className="rounded-[28px]" />
      </div>
    </div>
  );
}

function isEmptyDataError(message: string | null) {
  if (!message) {
    return false;
  }
  const normalized = message.toLowerCase();
  return normalized.includes("no scored sessions") || normalized.includes("no reps") || normalized.includes("no coaching data");
}

export function CoachingLabPage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<PeriodKey>("30");
  const [data, setData] = useState<CoachingAnalyticsResponse | null>(null);
  const [summary, setSummary] = useState<TeamCoachingSummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [weeklyBriefing, setWeeklyBriefing] = useState<WeeklyTeamBriefingResponse | null>(null);
  const [weeklyBriefingLoading, setWeeklyBriefingLoading] = useState(true);
  const [weeklyBriefingError, setWeeklyBriefingError] = useState<string | null>(null);
  const [weeklyBriefingExpanded, setWeeklyBriefingExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const analyticsRequestRef = useRef(0);
  const summaryRequestRef = useRef(0);
  const weeklyBriefingRequestRef = useRef(0);

  function openReplay(sessionId?: string, focusTurnId?: string | null) {
    if (!sessionId) {
      return;
    }
    const params = new URLSearchParams();
    if (focusTurnId) params.set("turnId", focusTurnId);
    navigate(`/manager/sessions/${sessionId}/replay${params.toString() ? `?${params.toString()}` : ""}`);
  }

  const loadSummary = useCallback(async () => {
    if (!managerId) return;
    const requestId = ++summaryRequestRef.current;
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const [result] = await Promise.allSettled([
        fetchTeamCoachingSummary(managerId, Number(period)),
      ]);
      if (summaryRequestRef.current !== requestId) {
        return;
      }
      if (result.status === "fulfilled") {
        setSummary(result.value);
        return;
      }
      if (isAuthError(result.reason)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setSummaryError(result.reason instanceof Error ? result.reason.message : "Failed to generate team coaching summary");
    } finally {
      if (summaryRequestRef.current === requestId) {
        setSummaryLoading(false);
      }
    }
  }, [managerId, navigate, period]);

  const loadWeeklyBriefing = useCallback(async () => {
    if (!managerId) return;
    const requestId = ++weeklyBriefingRequestRef.current;
    setWeeklyBriefingLoading(true);
    setWeeklyBriefingError(null);
    try {
      const response = await fetchWeeklyTeamBriefing(managerId);
      if (weeklyBriefingRequestRef.current !== requestId) {
        return;
      }
      setWeeklyBriefing(response);
    } catch (loadError) {
      if (isAuthError(loadError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      if (weeklyBriefingRequestRef.current !== requestId) {
        return;
      }
      setWeeklyBriefingError(loadError instanceof Error ? loadError.message : "Failed to load weekly briefing");
    } finally {
      if (weeklyBriefingRequestRef.current === requestId) {
        setWeeklyBriefingLoading(false);
      }
    }
  }, [managerId, navigate]);

  const loadData = useCallback(async () => {
    if (!managerId) return;
    const requestId = ++analyticsRequestRef.current;
    setLoading(true);
    setError(null);
    void loadSummary();
    void loadWeeklyBriefing();
    try {
      const [result] = await Promise.allSettled([
        fetchManagerCoachingAnalytics(managerId, { period }),
      ]);
      if (analyticsRequestRef.current !== requestId) {
        return;
      }
      if (result.status === "fulfilled") {
        setData(result.value);
        return;
      }
      if (isAuthError(result.reason)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(result.reason instanceof Error ? result.reason.message : "Failed to load coaching analytics");
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load coaching analytics");
    } finally {
      if (analyticsRequestRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [loadSummary, loadWeeklyBriefing, managerId, navigate, period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const upliftChart = useMemo(
    () =>
      (data?.coaching_uplift ?? [])
        .filter((item) => typeof item.delta === "number")
        .slice(0, 10)
        .map((item) => ({ rep_name: item.rep_name, delta: item.delta ?? 0 })),
    [data?.coaching_uplift]
  );

  const tagChart = useMemo(
    () => (data?.weakness_tag_uplift ?? []).slice(0, 8).map((item) => ({ ...item, delta_pct: item.delta })),
    [data?.weakness_tag_uplift]
  );

  const calibrationChart = useMemo(
    () => (data?.manager_calibration ?? []).map((item) => ({ ...item, avg_delta: item.average_override_delta ?? 0 })),
    [data?.manager_calibration]
  );
  const retryChart = useMemo(
    () => (data?.retry_impact ?? []).slice(0, 8).map((item) => ({ label: `${item.rep_name}`, delta: item.delta })),
    [data?.retry_impact]
  );
  const driftTimeline = useMemo(
    () => (data?.calibration_drift_timeline ?? []).map((item) => ({ ...item, avg_abs: item.average_absolute_delta ?? 0 })),
    [data?.calibration_drift_timeline]
  );
  const interventionTimeline = useMemo(
    () => (data?.intervention_timeline ?? []).map((item) => ({ ...item })),
    [data?.intervention_timeline]
  );

  if (loading) return <CoachingLabSkeleton />;
  if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  if (!data) return <EmptyState variant="empty" message="No coaching data available yet." />;

  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.header variants={cardVariants} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-3xl font-black tracking-tight text-ink">Coaching Lab</h1>
          <p className="mt-1 text-sm text-muted">Measure coaching uplift, review behavior, and calibration drift.</p>
        </div>
        <div className="flex rounded-2xl border border-white/35 bg-white/55 p-1">
          {PERIOD_OPTIONS.map((option) => (
            <button
              key={option.key}
              onClick={() => setPeriod(option.key)}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${period === option.key ? "bg-accent text-white" : "text-muted hover:bg-white/70 hover:text-ink"}`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </motion.header>

      <motion.section
        variants={cardVariants}
        className="rounded-[36px] border border-white/30 bg-white/45 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="flex flex-col gap-4 border-b border-white/20 pb-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Weekly Briefing</div>
              <h2 className="mt-2 text-2xl font-black tracking-tight text-ink">Monday-morning team readout</h2>
              <p className="mt-2 text-sm text-muted">
                Team pulse, standout rep, huddle angle, and action items from the last 7 days.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Toggle huddle topic details"
              onClick={() => setWeeklyBriefingExpanded((current) => !current)}
              className="inline-flex items-center gap-2 rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm font-medium text-ink transition hover:bg-white/80"
            >
              Huddle topic
              {weeklyBriefingExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            <button
              type="button"
              aria-label="Refresh weekly team briefing"
              onClick={() => void loadWeeklyBriefing()}
              disabled={weeklyBriefingLoading}
              className="inline-flex items-center gap-2 rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm font-medium text-ink transition hover:bg-white/80 disabled:opacity-60"
            >
              <RefreshCcw className={`h-4 w-4 ${weeklyBriefingLoading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        <div className="mt-6">
          {weeklyBriefingLoading && !weeklyBriefing ? <WeeklyBriefingSkeleton /> : null}

          {!weeklyBriefingLoading && !weeklyBriefing && weeklyBriefingError && isEmptyDataError(weeklyBriefingError) ? (
            <EmptyState variant="empty" message="No weekly team briefing is available yet." />
          ) : null}

          {!weeklyBriefingLoading && !weeklyBriefing && weeklyBriefingError && !isEmptyDataError(weeklyBriefingError) ? (
            <div className="rounded-[28px] border border-error/15 bg-error/[0.06] px-5 py-5 text-sm text-error">
              {weeklyBriefingError}
            </div>
          ) : null}

          {weeklyBriefing ? (
            <div className="space-y-5">
              {weeklyBriefingLoading ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900">
                  Refreshing weekly briefing...
                </div>
              ) : null}

              {!weeklyBriefingLoading && weeklyBriefingError ? (
                <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-3 text-sm text-error">
                  {weeklyBriefingError}
                </div>
              ) : null}

              <div className="rounded-[28px] border border-white/30 bg-white/60 p-5">
                <p className="text-lg font-semibold leading-8 text-ink">{weeklyBriefing.team_pulse}</p>
                <AiMetaStrip meta={weeklyBriefing.ai_meta} />
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
                <div className="space-y-4 rounded-[28px] border border-white/30 bg-white/55 p-5">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Standout Rep</div>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <span className="rounded-full bg-accent px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white">
                        {weeklyBriefing.standout_rep.name}
                      </span>
                      <p className="text-sm leading-6 text-ink">{weeklyBriefing.standout_rep.why}</p>
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Needs Attention</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {weeklyBriefing.needs_attention.length ? (
                        weeklyBriefing.needs_attention.map((item) => (
                          <div
                            key={item.name}
                            className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900"
                          >
                            <div className="flex items-center gap-2 font-semibold">
                              <AlertTriangle className="h-4 w-4" />
                              {item.name}
                            </div>
                            <p className="mt-2 leading-6">{item.concern}</p>
                            <div className="mt-3">
                              <button
                                type="button"
                                aria-label={`Assign drill for ${item.name}`}
                                onClick={() =>
                                  navigate("/manager/assignments/new", {
                                    state: buildAssignmentPrefillState(item.assignment_suggestion, {
                                      prefillRepIds: item.rep_id ? [item.rep_id] : undefined,
                                    }),
                                  })
                                }
                                className="inline-flex items-center gap-2 rounded-xl bg-white/80 px-3 py-2 text-xs font-semibold text-amber-950 transition hover:bg-white"
                              >
                                Assign Drill
                              </button>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-white/30 bg-white/60 px-4 py-3 text-sm text-muted">
                          No reps are currently flagged for immediate attention.
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="space-y-4 rounded-[28px] border border-white/30 bg-white/55 p-5">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Shared Weakness</div>
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <h3 className="text-lg font-bold tracking-tight text-ink">{weeklyBriefing.shared_weakness.skill}</h3>
                      <span className="rounded-full border border-white/35 bg-white/75 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-ink">
                        {weeklyBriefing.shared_weakness.team_average.toFixed(1)}/10
                      </span>
                    </div>
                    <div className="mt-4 h-3 overflow-hidden rounded-full bg-white/70">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-accent"
                        style={{ width: `${Math.max(8, Math.min(100, (weeklyBriefing.shared_weakness.team_average / 10) * 100))}%` }}
                      />
                    </div>
                    <p className="mt-3 text-sm leading-6 text-ink">{weeklyBriefing.shared_weakness.note}</p>
                  </div>

                  <div className="rounded-2xl border border-white/30 bg-white/70 p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Action Items</div>
                    <div className="mt-3 space-y-3">
                      {weeklyBriefing.manager_action_items.length ? (
                        weeklyBriefing.manager_action_items.map((item) => (
                          <label key={item} className="flex items-start gap-3 text-sm text-ink">
                            <input type="checkbox" aria-label={item} className="mt-1 h-4 w-4 rounded border-white/40 accent-accent" />
                            <span className="leading-6">{item}</span>
                          </label>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-white/30 bg-white/60 px-4 py-3 text-sm text-muted">
                          No manager follow-up actions were generated for this week.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden rounded-[28px] border border-white/30 bg-white/55">
                <button
                  type="button"
                  aria-label="Toggle weekly huddle topic"
                  onClick={() => setWeeklyBriefingExpanded((current) => !current)}
                  className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
                >
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Huddle Topic</div>
                    <h3 className="mt-2 text-lg font-bold tracking-tight text-ink">{weeklyBriefing.huddle_topic.topic}</h3>
                  </div>
                  {weeklyBriefingExpanded ? <ChevronUp className="h-5 w-5 text-muted" /> : <ChevronDown className="h-5 w-5 text-muted" />}
                </button>

                {weeklyBriefingExpanded ? (
                  <div className="border-t border-white/25 px-5 py-4">
                    {weeklyBriefing.huddle_topic.suggested_talking_points.length ? (
                      <ul className="space-y-3">
                        {weeklyBriefing.huddle_topic.suggested_talking_points.map((point) => (
                          <li key={point} className="flex items-start gap-3 text-sm leading-6 text-ink">
                            <span className="mt-2 h-2 w-2 rounded-full bg-accent" />
                            <span>{point}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm leading-6 text-muted">No suggested huddle talking points are available yet.</p>
                    )}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent/10 text-accent">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">AI Team Summary</h2>
              <p className="mt-1 text-sm text-muted">
                {summary ? `Generated ${formatRelativeTime(summary.generated_at)}` : "Cross-rep coaching pattern analysis"}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Regenerate team coaching summary"
            onClick={() => void loadSummary()}
            disabled={summaryLoading}
            className="inline-flex items-center gap-2 self-start rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm font-medium text-ink transition hover:bg-white/80 disabled:opacity-60"
          >
            <RefreshCcw className={`h-4 w-4 ${summaryLoading ? "animate-spin" : ""}`} />
            Regenerate
          </button>
        </div>

        <div className="mt-5">
          {summaryLoading && !summary ? (
            <div className="space-y-3">
              <div className="h-4 w-full animate-pulse rounded-full bg-white/35" />
              <div className="h-4 w-11/12 animate-pulse rounded-full bg-white/35" />
              <div className="h-4 w-4/5 animate-pulse rounded-full bg-white/35" />
            </div>
          ) : null}

          {!summaryLoading && !summary && summaryError && isEmptyDataError(summaryError) ? (
            <EmptyState variant="empty" message="No team coaching summary is available yet." />
          ) : null}

          {!summaryLoading && !summary && summaryError && !isEmptyDataError(summaryError) ? (
            <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-4 text-sm text-error">
              {summaryError}
            </div>
          ) : null}

          {summary ? (
            <div className="space-y-4">
              {summaryLoading ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900">
                  Refreshing team coaching summary...
                </div>
              ) : null}

              {!summaryLoading && summaryError ? (
                isEmptyDataError(summaryError) ? (
                  <div className="rounded-2xl border border-white/30 bg-white/60 px-4 py-4 text-sm text-muted">
                    No coaching summary is available for this period yet.
                  </div>
                ) : (
                  <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-4 text-sm text-error">
                    {summaryError}
                  </div>
                )
              ) : null}

              <p className="text-base leading-7 text-ink">{summary.summary}</p>
              <div className="flex flex-wrap items-center gap-3">
                <AiMetaStrip meta={summary.ai_meta} />
                <button
                  type="button"
                  aria-label="Open assignment builder"
                  onClick={() => navigate("/manager/assignments/new")}
                  className="inline-flex items-center gap-2 rounded-xl border border-white/35 bg-white/70 px-3 py-2 text-sm font-semibold text-ink transition hover:bg-white"
                >
                  Assign Drill
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-4">
        {[
          { label: "Coaching Notes", value: String(data.summary.coaching_note_count), icon: BookOpenText },
          { label: "Reviews", value: String(data.summary.review_count), icon: MessageSquareQuote },
          { label: "Override Rate", value: formatPercent(data.summary.override_rate), icon: Scale },
          {
            label: "Avg Override Δ",
            value: typeof data.summary.average_override_delta === "number" ? `${data.summary.average_override_delta >= 0 ? "+" : ""}${data.summary.average_override_delta.toFixed(1)}` : "--",
            icon: TrendingUp,
          },
          {
            label: "Retry Uplift",
            value: typeof data.summary.retry_uplift_avg === "number" ? `${data.summary.retry_uplift_avg >= 0 ? "+" : ""}${data.summary.retry_uplift_avg.toFixed(1)}` : "--",
            icon: TrendingUp,
          },
          {
            label: "Coached Retry Δ",
            value: typeof data.summary.coached_retry_uplift_avg === "number" ? `${data.summary.coached_retry_uplift_avg >= 0 ? "+" : ""}${data.summary.coached_retry_uplift_avg.toFixed(1)}` : "--",
            icon: TrendingUp,
          },
          {
            label: "Improved Interventions",
            value: typeof data.summary.intervention_improved_rate === "number" ? formatPercent(data.summary.intervention_improved_rate) : "--",
            icon: BookOpenText,
          },
          {
            label: "Drift Score",
            value: typeof data.summary.calibration_drift_score === "number" ? data.summary.calibration_drift_score.toFixed(2) : "--",
            icon: Scale,
          },
        ].map((card) => (
          <motion.div
            key={card.label}
            variants={cardVariants}
            className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{card.label}</div>
                <div className="mt-3 text-3xl font-black tracking-tight text-ink">{card.value}</div>
              </div>
              <div className="rounded-2xl bg-accent/10 p-3 text-accent">
                <card.icon className="h-5 w-5" />
              </div>
            </div>
          </motion.div>
        ))}
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Coaching Uplift by Rep</h2>
          <div className="mt-4 h-[300px] w-full">
            {upliftChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={upliftChart} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="rep_name" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="delta" radius={[12, 12, 0, 0]} fill="#2d5a3d" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No before/after coaching samples yet." />
            )}
          </div>
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Weakness Tag Uplift</h2>
          <div className="mt-4 h-[300px] w-full">
            {tagChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tagChart} layout="vertical" margin={{ top: 10, right: 10, left: 20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="tag" width={120} tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="delta_pct" radius={[0, 12, 12, 0]} fill="#b77a13" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No tag-level uplift yet." />
            )}
          </div>
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Retry Impact</h2>
          <div className="mt-4 h-[280px] w-full">
            {retryChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={retryChart} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="delta" radius={[12, 12, 0, 0]} fill="#2d5a3d" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No repeat-attempt score deltas yet." />
            )}
          </div>
          <div className="mt-4 space-y-3">
            {(data.retry_impact ?? []).slice(0, 5).map((item) => (
              <button
                key={`${item.from_session_id}-${item.to_session_id}`}
                onClick={() => openReplay(item.to_session_id)}
                className="flex w-full items-center justify-between rounded-2xl border border-white/25 bg-white/45 px-4 py-3 text-left transition hover:bg-white/65"
              >
                <div>
                  <div className="text-sm font-semibold text-ink">{item.rep_name}</div>
                  <div className="mt-1 text-xs text-muted">{item.scenario_name} · {item.coached_between_attempts ? "coached retry" : "retry"}</div>
                </div>
                <div className="text-sm font-bold text-ink">{item.delta >= 0 ? "+" : ""}{item.delta.toFixed(1)}</div>
              </button>
            ))}
          </div>
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Calibration Drift Timeline</h2>
          <div className="mt-4 h-[280px] w-full">
            {driftTimeline.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={driftTimeline} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="avg_abs" radius={[12, 12, 0, 0]} fill="#b77a13" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No calibration drift timeline yet." />
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {(data.intervention_segments ?? []).map((segment) => (
              <span key={`${segment.visibility}-${segment.outcome}`} className="rounded-full bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink">
                {segment.visibility} · {segment.outcome} · {segment.count}
              </span>
            ))}
          </div>
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Calibration Drift</h2>
          <div className="mt-4 h-[300px] w-full">
            {calibrationChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={calibrationChart} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="reviewer_name" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="avg_delta" radius={[12, 12, 0, 0]} fill="#2d5a3d" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No override calibration data yet." />
            )}
          </div>
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Recent Coaching Notes</h2>
          <div className="mt-4 space-y-3">
            {data.recent_notes.length ? (
              data.recent_notes.map((note) => (
                <button
                  key={note.id}
                  onClick={() => openReplay(note.session_id, note.focus_turn_id)}
                  className="w-full rounded-2xl border border-white/25 bg-white/45 p-4 text-left transition hover:bg-white/60"
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-ink">{note.rep_name}</div>
                      <div className="mt-1 text-xs text-muted">{note.scenario_name} · {new Date(note.created_at).toLocaleString()}</div>
                      <p className="mt-3 text-sm leading-6 text-ink">{note.note}</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {note.weakness_tags.map((tag) => (
                          <span key={tag} className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${note.visible_to_rep ? "bg-accent-soft text-accent" : "bg-white/70 text-muted"}`}>
                      {note.visible_to_rep ? "rep-visible" : "private"}
                    </span>
                  </div>
                </button>
              ))
            ) : (
              <EmptyState variant="empty" message="No coaching notes have been added yet." />
            )}
          </div>
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Intervention Timeline</h2>
          <div className="mt-4 h-[280px] w-full">
            {interventionTimeline.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={interventionTimeline} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="review_count" radius={[12, 12, 0, 0]} fill="#2d5a3d" />
                  <Bar dataKey="coaching_note_count" radius={[12, 12, 0, 0]} fill="#b77a13" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No intervention timeline yet." />
            )}
          </div>
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="text-lg font-bold tracking-tight text-ink">Scenario Drift Watchlist</h2>
          <div className="mt-4 space-y-3">
            {(data.score_drift_by_scenario ?? []).length ? (
              (data.score_drift_by_scenario ?? []).map((item) => (
                <div key={item.scenario_id} className="rounded-2xl border border-white/25 bg-white/45 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-ink">{item.scenario_name}</div>
                      <div className="mt-1 text-xs text-muted">{item.review_count} reviewed sessions</div>
                    </div>
                    <div className="grid gap-3 text-sm sm:grid-cols-2">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Avg Δ</div>
                        <div className="mt-1 font-bold text-ink">
                          {typeof item.average_delta === "number" ? `${item.average_delta >= 0 ? "+" : ""}${item.average_delta.toFixed(1)}` : "--"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Avg |Δ|</div>
                        <div className="mt-1 font-bold text-ink">
                          {typeof item.average_absolute_delta === "number" ? item.average_absolute_delta.toFixed(1) : "--"}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState variant="empty" message="No scenario drift signals yet." />
            )}
          </div>
        </motion.div>
      </motion.section>
    </motion.main>
  );
}
