import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowRight, Check, Copy, RefreshCcw, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ReferenceLine,
} from "recharts";

import { OneOnOnePrepCard } from "../components/OneOnOnePrepCard";
import { RepRadarChart } from "../components/RepRadarChart";
import { ChartSkeleton } from "../components/shared/ChartSkeleton";
import { EmptyState } from "../components/shared/EmptyState";
import { AiMetaStrip } from "../components/shared/AiMetaStrip";
import { ScoreTrajectoryBar } from "../components/shared/ScoreTrajectoryBar";
import { ScoreChip } from "../components/shared/ScoreChip";
import { SkillChip } from "../components/shared/SkillChip";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerFeed, fetchRepInsight, fetchRepProgress, fetchRepRiskDetail } from "../lib/api";
import {
  CATEGORY_META,
  PASSING_SCORE,
  averageCategoryScores,
  emptyCategoryRecord,
  getCategoryLabel,
  normalizeCategoryKey,
  type AnalyticsCategoryKey,
} from "../lib/analytics";
import { cardVariants, pageVariants } from "../lib/motion";
import { resolvePeriodWindow } from "../lib/periods";
import type { FeedItem, RepInsightResponse, RepProgress, RepRiskDetail } from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "7", label: "7D" },
  { key: "30", label: "30D" },
  { key: "90", label: "90D" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];
type GapSummary = {
  category: AnalyticsCategoryKey;
  delta: number;
};

function formatDuration(durationSeconds?: number | null): string {
  if (!durationSeconds) {
    return "--";
  }
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = durationSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatRelativeTime(timestamp?: string | null): string {
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
  const deltaDays = Math.round(deltaHours / 24);
  return `${deltaDays}d ago`;
}

function parseDrillRecommendation(recommendation: string): { scenarioSearch: string; difficulty?: number } {
  const quoted = recommendation.match(/["']([^"']+)["']/)?.[1]?.trim();
  const difficultyMatch = recommendation.match(/difficulty\s*(\d+)/i);
  const difficulty = difficultyMatch ? Number(difficultyMatch[1]) : undefined;
  const scenarioSearch = quoted ?? recommendation.replace(/assign:?/i, "").replace(/difficulty\s*\d+/i, "").trim();
  return {
    scenarioSearch: scenarioSearch || recommendation,
    difficulty: Number.isFinite(difficulty) ? difficulty : undefined,
  };
}

function formatTrajectoryScore(value: number | null | undefined): string {
  if (typeof value !== "number") {
    return "--";
  }
  return value.toFixed(1);
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

function formatAdaptiveSkillLabel(skill: string): string {
  return skill
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function InsightSkeleton() {
  return (
    <div className="space-y-4">
      <div className="h-4 w-40 animate-pulse rounded-full bg-white/45" />
      <div className="h-8 w-3/4 animate-pulse rounded-full bg-white/40" />
      <div className="grid gap-3 md:grid-cols-2">
        <div className="h-24 animate-pulse rounded-2xl bg-white/35" />
        <div className="h-24 animate-pulse rounded-2xl bg-white/35" />
      </div>
      <div className="h-16 animate-pulse rounded-2xl bg-white/35" />
      <div className="h-28 animate-pulse rounded-2xl bg-white/35" />
    </div>
  );
}

function RepProgressSkeleton() {
  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.div variants={cardVariants} className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <ChartSkeleton heightClass="h-4" className="max-w-[120px]" />
          <ChartSkeleton heightClass="h-10" className="max-w-[220px]" />
          <ChartSkeleton heightClass="h-4" className="max-w-[260px]" />
        </div>
        <ChartSkeleton heightClass="h-11" className="w-full max-w-[180px]" />
      </motion.div>

      <motion.section variants={cardVariants} className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <ChartSkeleton key={index} heightClass="h-28" />
        ))}
      </motion.section>

      <motion.section variants={cardVariants}>
        <ChartSkeleton heightClass="h-[160px]" className="rounded-[32px]" />
      </motion.section>

      <motion.section variants={cardVariants}>
        <ChartSkeleton heightClass="h-[320px]" className="rounded-[32px]" />
      </motion.section>

      <motion.section variants={cardVariants} className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ChartSkeleton heightClass="h-[420px]" className="rounded-[32px]" />
        <ChartSkeleton heightClass="h-[420px]" className="rounded-[32px]" />
      </motion.section>

      <motion.section variants={cardVariants}>
        <ChartSkeleton heightClass="h-[360px]" className="rounded-[32px]" />
      </motion.section>
    </motion.main>
  );
}

export function RepProgressPage() {
  const { id } = useParams<{ id: string }>();
  const repId = id || "unknown";
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<PeriodKey>("30");
  const [progress, setProgress] = useState<RepProgress | null>(null);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [riskDetail, setRiskDetail] = useState<RepRiskDetail | null>(null);
  const [insight, setInsight] = useState<RepInsightResponse | null>(null);
  const [insightLoading, setInsightLoading] = useState(true);
  const [insightError, setInsightError] = useState<string | null>(null);
  const [copiedScript, setCopiedScript] = useState(false);
  const [prepOpen, setPrepOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const coreRequestRef = useRef(0);
  const insightRequestRef = useRef(0);

  const periodWindow = useMemo(() => resolvePeriodWindow(period), [period]);
  const focusCategory = normalizeCategoryKey(searchParams.get("category"));

  const loadInsight = useCallback(async () => {
    if (!managerId) {
      return;
    }
    const requestId = ++insightRequestRef.current;
    setInsightLoading(true);
    setInsightError(null);
    try {
      const [result] = await Promise.allSettled([
        fetchRepInsight(managerId, repId, periodWindow.current.spanDays),
      ]);
      if (insightRequestRef.current !== requestId) {
        return;
      }
      if (result.status === "fulfilled") {
        setInsight(result.value);
        setInsightError(null);
        return;
      }
      if (isAuthError(result.reason)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setInsightError(result.reason instanceof Error ? result.reason.message : "Could not generate analysis. Try refreshing.");
    } finally {
      if (insightRequestRef.current === requestId) {
        setInsightLoading(false);
      }
    }
  }, [managerId, navigate, periodWindow.current.spanDays, repId]);

  const loadData = useCallback(async () => {
    if (!managerId) {
      return;
    }

    const requestId = ++coreRequestRef.current;
    setLoading(true);
    setError(null);
    setRiskDetail(null);
    void loadInsight();

    const [progressResult, feedResult, riskResult] = await Promise.allSettled([
      fetchRepProgress(managerId, repId, {
        days: periodWindow.current.spanDays,
        dateFrom: periodWindow.current.startInput,
        dateTo: periodWindow.current.endInput,
        limit: 60,
      }),
      fetchManagerFeed(managerId, {
        repId,
        dateFrom: periodWindow.previous.startInput,
        dateTo: periodWindow.current.endInput,
        limit: 500,
      }),
      fetchRepRiskDetail(managerId, { period: String(periodWindow.current.spanDays) }),
    ]);

    if (coreRequestRef.current !== requestId) {
      return;
    }

    const authFailure = [progressResult, feedResult, riskResult].find(
      (result) => result.status === "rejected" && isAuthError(result.reason)
    );
    if (authFailure) {
      clearStoredAuth();
      navigate("/login", { replace: true });
      return;
    }

    if (progressResult.status === "rejected") {
      setError(progressResult.reason instanceof Error ? progressResult.reason.message : "Failed to fetch rep progress");
      setLoading(false);
      return;
    }

    if (feedResult.status === "rejected") {
      setError(feedResult.reason instanceof Error ? feedResult.reason.message : "Failed to fetch rep feed");
      setLoading(false);
      return;
    }

    setProgress(progressResult.value);
    setFeed(feedResult.value.filter((item) => item.rep_id === repId));
    setRiskDetail(
      riskResult.status === "fulfilled"
        ? riskResult.value.reps.find((item) => item.rep_id === repId) ?? null
        : null
    );
    setLoading(false);
  }, [loadInsight, managerId, navigate, periodWindow.current.endInput, periodWindow.current.spanDays, periodWindow.current.startInput, periodWindow.previous.startInput, repId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (!copiedScript) {
      return;
    }
    const timer = window.setTimeout(() => setCopiedScript(false), 1400);
    return () => window.clearTimeout(timer);
  }, [copiedScript]);

  const repName = feed[0]?.rep_name ?? progress?.rep_name ?? repId;

  const filteredSessions = useMemo(() => {
    const currentStart = periodWindow.current.start.getTime();
    const currentEnd = periodWindow.current.end.getTime();
    const previousStart = periodWindow.previous.start.getTime();
    const previousEnd = periodWindow.previous.end.getTime();

    const current = feed.filter((session) => {
      if (!session.started_at) {
        return false;
      }
      const startedAt = new Date(session.started_at).getTime();
      return Number.isFinite(startedAt) && startedAt >= currentStart && startedAt <= currentEnd;
    });

    const previous = feed.filter((session) => {
      if (!session.started_at) {
        return false;
      }
      const startedAt = new Date(session.started_at).getTime();
      return Number.isFinite(startedAt) && startedAt >= previousStart && startedAt <= previousEnd;
    });

    return { current, previous };
  }, [feed, periodWindow.current.end, periodWindow.current.start, periodWindow.previous.end, periodWindow.previous.start]);

  const currentCategoryAverages = useMemo(() => {
    if (filteredSessions.current.length) {
      return averageCategoryScores(filteredSessions.current);
    }

    return CATEGORY_META.reduce<Record<string, number>>((accumulator, category) => {
      accumulator[category.key] = progress?.current_period_category_averages?.[category.key] ?? 0;
      return accumulator;
    }, {});
  }, [filteredSessions.current, progress?.current_period_category_averages]);

  const previousCategoryAverages = useMemo(() => {
    if (!filteredSessions.previous.length) {
      return emptyCategoryRecord();
    }
    return averageCategoryScores(filteredSessions.previous);
  }, [filteredSessions.previous]);

  const benchmarkCategoryAverages = useMemo(() => {
    if (!feed.length) {
      return emptyCategoryRecord();
    }
    return averageCategoryScores(feed);
  }, [feed]);

  const weakSkills = useMemo(() => {
    return CATEGORY_META
      .map((category) => ({
        key: category.key,
        label: getCategoryLabel(category.key),
        score: currentCategoryAverages[category.key] ?? 0,
      }))
      .filter((category) => category.score < PASSING_SCORE)
      .sort((left, right) => left.score - right.score);
  }, [currentCategoryAverages]);

  const biggestGap = useMemo(() => {
    return CATEGORY_META.reduce<GapSummary>(
      (lowest, category) => {
        const currentScore = currentCategoryAverages[category.key] ?? 0;
        const benchmark = benchmarkCategoryAverages[category.key] ?? 0;
        const delta = Number((currentScore - benchmark).toFixed(2));
        if (delta < lowest.delta) {
          return { category: category.key, delta };
        }
        return lowest;
      },
      { category: CATEGORY_META[0].key, delta: Number.POSITIVE_INFINITY }
    );
  }, [benchmarkCategoryAverages, currentCategoryAverages]);

  const focusCategorySummary = useMemo(() => {
    if (!focusCategory) {
      return null;
    }
    const currentScore = currentCategoryAverages[focusCategory] ?? 0;
    const benchmark = benchmarkCategoryAverages[focusCategory] ?? 0;
    return {
      label: getCategoryLabel(focusCategory),
      currentScore,
      benchmark,
      delta: Number((currentScore - benchmark).toFixed(2)),
    };
  }, [benchmarkCategoryAverages, currentCategoryAverages, focusCategory]);

  const scoredSessions = useMemo(
    () => (progress?.latest_sessions ?? []).filter((session) => typeof session.overall_score === "number"),
    [progress]
  );

  const bestScore = useMemo(() => {
    if (!scoredSessions.length) {
      return "--";
    }
    return Math.max(...scoredSessions.map((session) => session.overall_score ?? 0)).toFixed(1);
  }, [scoredSessions]);

  const lineData = useMemo(() => {
    return (progress?.trend ?? []).map((session) => ({
      date: session.started_at
        ? new Date(session.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })
        : "Unknown",
      score: session.overall_score ?? 0,
    }));
  }, [progress]);

  const trendDelta = useMemo(() => {
    const scores = (progress?.trend ?? [])
      .map((session) => session.overall_score)
      .filter((score): score is number => typeof score === "number");
    if (scores.length < 2) {
      return null;
    }
    return Number((scores[scores.length - 1] - scores[0]).toFixed(2));
  }, [progress?.trend]);

  const trajectoryCurrentScore = riskDetail?.current_avg_score ?? progress?.average_score ?? null;
  const trajectoryProjectedScore = riskDetail?.projected_score_10_sessions ?? null;
  const trajectorySlope = riskDetail?.score_trend_slope ?? null;
  const trajectoryWarning =
    typeof trajectoryProjectedScore === "number" && trajectoryProjectedScore < 6;

  const sessionRows = useMemo(() => {
    const feedBySessionId = new Map(feed.map((item) => [item.session_id, item]));
    return (progress?.latest_sessions ?? []).map((session, index, sessions) => {
      const previousScore = sessions[index + 1]?.overall_score;
      const scoreDelta =
        typeof session.overall_score === "number" && typeof previousScore === "number"
          ? Number((session.overall_score - previousScore).toFixed(2))
          : null;
      return {
        ...session,
        previousScore,
        scoreDelta,
        feed: feedBySessionId.get(session.session_id),
      };
    });
  }, [feed, progress]);

  const drillPrefill = useMemo(
    () => (insight ? parseDrillRecommendation(insight.drill_recommendation) : null),
    [insight]
  );

  const adaptiveTrajectoryNodes = useMemo(() => {
    if (!insight?.adaptive_skill_profile?.length) {
      return [];
    }
    return [...insight.adaptive_skill_profile]
      .sort((left, right) => left.score - right.score)
      .slice(0, 3);
  }, [insight]);

  const adaptiveTrajectoryData = useMemo(() => {
    if (!insight || !adaptiveTrajectoryNodes.length) {
      return [];
    }
    const projectionLabel =
      typeof insight.readiness_trajectory?.sessions_to_readiness === "number"
        ? insight.readiness_trajectory.sessions_to_readiness === 0
          ? "Ready now"
          : `+${insight.readiness_trajectory.sessions_to_readiness} sessions`
        : "Projection";
    const projectedScores = insight.readiness_trajectory?.trajectory_per_skill ?? {};
    return [
      adaptiveTrajectoryNodes.reduce<Record<string, string | number>>(
        (record, node) => {
          record.phase = "Now";
          record[node.skill] = node.score;
          return record;
        },
        {}
      ),
      adaptiveTrajectoryNodes.reduce<Record<string, string | number>>(
        (record, node) => {
          record.phase = projectionLabel;
          record[node.skill] = projectedScores[node.skill] ?? node.score;
          return record;
        },
        {}
      ),
    ];
  }, [adaptiveTrajectoryNodes, insight]);

  const overrideSignalSummary = useMemo(() => {
    if (!insight?.override_signal) {
      return null;
    }
    const normalizedCategory = insight.override_signal.most_overridden_category
      ? normalizeCategoryKey(insight.override_signal.most_overridden_category)
      : null;
    return {
      overrideCount: insight.override_signal.override_count ?? 0,
      meanDelta: insight.override_signal.mean_delta ?? 0,
      mostOverriddenCategory: normalizedCategory
        ? getCategoryLabel(normalizedCategory as AnalyticsCategoryKey)
        : insight.override_signal.most_overridden_category
          ? formatAdaptiveSkillLabel(insight.override_signal.most_overridden_category)
          : null,
    };
  }, [insight]);

  const handleCopyScript = useCallback(async () => {
    if (!insight?.coaching_script || !navigator.clipboard?.writeText) {
      return;
    }
    try {
      await navigator.clipboard.writeText(insight.coaching_script);
      setCopiedScript(true);
    } catch {
      setCopiedScript(false);
    }
  }, [insight]);

  if (loading) {
    return <RepProgressSkeleton />;
  }

  if (error) {
    return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  }

  if (!progress) {
    return <EmptyState variant="empty" message="No data found for this rep." />;
  }

  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.header variants={cardVariants} className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link
            to="/manager/feed"
            className="mb-2 inline-block text-sm text-muted transition-colors hover:text-ink"
          >
            &larr; All Sessions
          </Link>
          <h1 className="text-3xl font-bold tracking-tight text-ink">Rep Progress</h1>
          <p className="mt-1 text-sm text-muted">
            {repName} · {progress.rep_id}
          </p>
          {focusCategorySummary ? (
            <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent-soft/65 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-accent">
              Focus {focusCategorySummary.label} · {focusCategorySummary.currentScore.toFixed(1)} vs{" "}
              {focusCategorySummary.benchmark.toFixed(1)}
            </div>
          ) : null}
        </div>
        <div className="flex flex-col items-start gap-3 sm:items-end">
          <div className="flex rounded-2xl border border-white/35 bg-white/55 p-1">
            {PERIOD_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                aria-label={`Show rep progress for ${option.label}`}
                onClick={() => setPeriod(option.key)}
                className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${period === option.key ? "bg-accent text-white" : "text-muted hover:bg-white/70 hover:text-ink"}`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              aria-label="Open one on one prep"
              onClick={() => setPrepOpen(true)}
              className="rounded-xl border border-white/35 bg-white/70 px-5 py-2.5 text-sm font-semibold text-ink transition hover:bg-white"
            >
              Prep 1:1
            </button>
            <button
              type="button"
              aria-label="Assign a new drill"
              onClick={() => navigate("/manager/assignments/new")}
              className="rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-accent/25 transition-colors hover:bg-accent-hover"
            >
              Assign Drill
            </button>
          </div>
        </div>
      </motion.header>

      <motion.section variants={cardVariants} className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {[
          { label: "Sessions Completed", value: String(progress.session_count) },
          { label: "Average Score", value: progress.average_score?.toFixed(1) ?? "--" },
          { label: "Best Score", value: bestScore },
          {
            label: "Improvement Δ",
            value: trendDelta === null ? "--" : `${trendDelta >= 0 ? "+" : ""}${trendDelta.toFixed(1)}`,
            delta: trendDelta,
          },
        ].map((card) => (
          <motion.div
            key={card.label}
            variants={cardVariants}
            className="rounded-2xl border border-white/30 bg-white/40 p-4 text-center shadow-xl shadow-black/5 backdrop-blur-2xl"
          >
            <span className="mb-1 block text-xs uppercase tracking-wide text-muted">{card.label}</span>
            {card.label === "Improvement Δ" ? (
              <div className="flex items-center justify-center gap-1">
                {(card.delta ?? 0) >= 0 ? (
                  <TrendingUp className="h-5 w-5 text-green-600" />
                ) : (
                  <TrendingDown className="h-5 w-5 text-red-600" />
                )}
                <strong className="text-2xl font-bold text-ink">{card.value}</strong>
              </div>
            ) : (
              <strong className="text-2xl font-bold text-ink">{card.value}</strong>
            )}
          </motion.div>
        ))}
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Score Trajectory</div>
            <h2 className="mt-2 text-xl font-black tracking-tight text-ink">
              {formatTrajectoryScore(trajectoryCurrentScore)} today → {formatTrajectoryScore(trajectoryProjectedScore)} projected
            </h2>
          </div>
          {trajectoryWarning ? (
            <div className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-50/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-red-700">
              <AlertTriangle className="h-4 w-4" />
              Watch Trend
            </div>
          ) : null}
        </div>

        <div className="mt-6">
          <ScoreTrajectoryBar
            currentScore={trajectoryCurrentScore}
            projectedScore={trajectoryProjectedScore}
            size="md"
          />
        </div>

        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
          <span>Trend: {trajectorySlope !== null ? `${trajectorySlope >= 0 ? "+" : ""}${trajectorySlope.toFixed(2)}/session` : "--"}</span>
          <span>Volatility: {riskDetail ? volatilityLabel(riskDetail.score_volatility) : "--"}</span>
          <span>Projection window: 10 sessions</span>
        </div>
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Adaptive Readiness</div>
            <h2 className="mt-2 text-xl font-black tracking-tight text-ink">Projected skill path to readiness</h2>
            <p className="mt-2 text-sm text-muted">
              Weakest adaptive skills now versus the projected readiness checkpoint from the AI coaching service.
            </p>

            <div className="mt-6">
              {insightLoading ? (
                <ChartSkeleton heightClass="h-[260px]" className="rounded-[28px]" />
              ) : insightError ? (
                <EmptyState variant="error" message={insightError} onRetry={() => void loadInsight()} />
              ) : !insight || !adaptiveTrajectoryData.length ? (
                <EmptyState variant="empty" message="Adaptive readiness projection is not available yet." />
              ) : (
                <div className="h-[260px] w-full rounded-[28px] border border-white/25 bg-white/55 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={adaptiveTrajectoryData} margin={{ top: 10, right: 20, left: -18, bottom: 0 }}>
                      <XAxis dataKey="phase" tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                      <YAxis domain={[0, 10]} tickCount={6} tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: "rgba(255,255,255,0.94)",
                          backdropFilter: "blur(10px)",
                          borderRadius: "12px",
                          border: "1px solid rgba(255,255,255,0.3)",
                        }}
                        itemStyle={{ color: "var(--color-ink)", fontWeight: 600 }}
                        labelStyle={{ color: "var(--color-muted)", fontSize: 12, marginBottom: 4 }}
                      />
                      <ReferenceLine y={7} stroke="#b77a13" strokeDasharray="4 4" opacity={0.65} />
                      {adaptiveTrajectoryNodes.map((node, index) => (
                        <Line
                          key={node.skill}
                          type="monotone"
                          dataKey={node.skill}
                          name={formatAdaptiveSkillLabel(node.skill)}
                          stroke={["#2d5a3d", "#b77a13", "#365314"][index % 3]}
                          strokeWidth={3}
                          dot={{ r: 4 }}
                          activeDot={{ r: 5 }}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-4">
            {insightLoading ? (
              <>
                <ChartSkeleton heightClass="h-[132px]" className="rounded-[28px]" />
                <ChartSkeleton heightClass="h-[120px]" className="rounded-[28px]" />
                <ChartSkeleton heightClass="h-[176px]" className="rounded-[28px]" />
              </>
            ) : insightError ? (
              <div className="rounded-[28px] border border-error/15 bg-error/[0.06] px-5 py-5">
                <p className="text-sm font-medium text-error">{insightError}</p>
                <button
                  type="button"
                  aria-label="Retry adaptive readiness insights"
                  onClick={() => void loadInsight()}
                  className="mt-4 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover"
                >
                  <RefreshCcw className="h-4 w-4" />
                  Retry
                </button>
              </div>
            ) : !insight ? (
              <EmptyState variant="empty" message="Adaptive readiness details are not available yet." />
            ) : (
              <>
                <div className="rounded-[28px] border border-white/25 bg-white/55 p-5">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Readiness ETA</div>
                  <div className="mt-3 text-2xl font-black tracking-tight text-ink">
                    {typeof insight.readiness_trajectory?.sessions_to_readiness === "number"
                      ? insight.readiness_trajectory.sessions_to_readiness === 0
                        ? "Ready now"
                        : `${insight.readiness_trajectory.sessions_to_readiness} sessions`
                      : "Not projected"}
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted">
                    {typeof insight.readiness_trajectory?.sessions_to_readiness === "number"
                      ? "Projected sessions until the weakest skills reach the readiness threshold."
                      : "Current growth rates are too flat to give a defensible readiness ETA."}
                  </p>
                </div>

                <div className="rounded-[28px] border border-white/25 bg-white/55 p-5">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Weakest Skills</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {adaptiveTrajectoryNodes.length ? (
                      adaptiveTrajectoryNodes.map((node) => (
                        <div key={node.skill} className="rounded-full border border-white/35 bg-white/75 px-3 py-1.5 text-sm font-medium text-ink">
                          {formatAdaptiveSkillLabel(node.skill)} {node.score.toFixed(1)}
                        </div>
                      ))
                    ) : (
                      <div className="text-sm text-muted">No adaptive skill profile available.</div>
                    )}
                  </div>
                </div>

                <div className="rounded-[28px] border border-white/25 bg-white/55 p-5">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Override Signal</div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-white/35 bg-white/75 p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Adjustments</div>
                      <div className="mt-2 text-2xl font-black tracking-tight text-ink">{overrideSignalSummary?.overrideCount ?? 0}</div>
                    </div>
                    <div className="rounded-2xl border border-white/35 bg-white/75 p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Mean Δ</div>
                      <div className="mt-2 text-2xl font-black tracking-tight text-ink">
                        {typeof overrideSignalSummary?.meanDelta === "number"
                          ? `${overrideSignalSummary.meanDelta >= 0 ? "+" : ""}${overrideSignalSummary.meanDelta.toFixed(1)}`
                          : "--"}
                      </div>
                    </div>
                  </div>
                  <p className="mt-4 text-sm leading-6 text-ink">
                    {overrideSignalSummary?.overrideCount
                      ? `Managers have adjusted AI scores ${overrideSignalSummary.overrideCount} times for this rep, with an average delta of ${overrideSignalSummary.meanDelta >= 0 ? "+" : ""}${overrideSignalSummary.meanDelta.toFixed(1)}${overrideSignalSummary.mostOverriddenCategory ? ` and the most corrected area being ${overrideSignalSummary.mostOverriddenCategory}.` : "."}`
                      : "No manager override pattern has been recorded for this rep yet."}
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">Score Trend</h2>
            <p className="mt-1 text-sm text-muted">Current-window session scores for the selected period.</p>
          </div>
          <div className="rounded-full border border-white/30 bg-white/50 px-3 py-1 text-xs font-medium text-ink">
            {period} days
          </div>
        </div>

        {lineData.length > 0 ? (
          <div className="h-[220px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lineData} margin={{ top: 5, right: 20, left: -20, bottom: 0 }}>
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12, fill: "var(--color-muted)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 10]}
                  tickCount={6}
                  tick={{ fontSize: 12, fill: "var(--color-muted)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <RechartsTooltip
                  contentStyle={{
                    backgroundColor: "rgba(255,255,255,0.92)",
                    backdropFilter: "blur(10px)",
                    borderRadius: "12px",
                    border: "1px solid rgba(255,255,255,0.3)",
                  }}
                  itemStyle={{ color: "var(--color-ink)", fontWeight: 600 }}
                  labelStyle={{ color: "var(--color-muted)", fontSize: 12, marginBottom: 4 }}
                />
                <ReferenceLine y={PASSING_SCORE} stroke="#fbbf24" strokeDasharray="3 3" opacity={0.5} />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="var(--color-accent)"
                  strokeWidth={2}
                  dot={{ fill: "var(--color-accent)", r: 3 }}
                  activeDot={{ r: 5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <EmptyState variant="empty" message="No sessions recorded yet." />
        )}
      </motion.section>

      <motion.section variants={cardVariants} className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-ink">Category Radar</h2>
              <p className="mt-1 text-sm text-muted">
                Current versus previous period performance, anchored to the rep&apos;s rolling category benchmark.
              </p>
            </div>
            {focusCategorySummary ? (
              <div className="rounded-full border border-white/35 bg-white/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-ink">
                {focusCategorySummary.label}
              </div>
            ) : null}
          </div>

          <RepRadarChart
            current={currentCategoryAverages}
            previous={previousCategoryAverages}
            benchmarks={benchmarkCategoryAverages}
            height={320}
          />

          <div className="mt-5 flex flex-wrap gap-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50/70 px-3 py-2 text-sm font-medium text-amber-900">
              Biggest Gap
              <ScoreChip score={currentCategoryAverages[biggestGap.category]} size="sm" />
              {getCategoryLabel(biggestGap.category)} {biggestGap.delta >= 0 ? "+" : ""}
              {biggestGap.delta.toFixed(1)} vs benchmark
            </div>
            {focusCategorySummary ? (
              <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/65 px-3 py-2 text-sm text-ink">
                Focus
                <ScoreChip score={focusCategorySummary.currentScore} size="sm" />
                {focusCategorySummary.delta >= 0 ? "+" : ""}
                {focusCategorySummary.delta.toFixed(1)} vs benchmark
              </div>
            ) : null}
          </div>
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="flex flex-col rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <h2 className="mb-4 text-base font-semibold text-ink">Weak Areas</h2>
          {weakSkills.length > 0 ? (
            <>
              <div className="mb-6 flex flex-wrap gap-2">
                {weakSkills.map((skill) => (
                  <SkillChip key={skill.key} label={skill.label} variant="weak" />
                ))}
              </div>
              <button
                type="button"
                aria-label="Assign a follow-up drill"
                onClick={() => navigate("/manager/assignments/new")}
                className="mt-auto flex w-full items-center justify-center gap-2 rounded-xl border border-white/30 bg-white/50 px-4 py-3 text-sm font-medium text-ink transition-colors hover:bg-white/70"
              >
                Assign Follow-Up Drill
                <ArrowRight className="h-4 w-4 text-muted" />
              </button>
            </>
          ) : (
            <EmptyState variant="empty" message="No categories are averaging below benchmark this period." />
          )}
        </motion.div>
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="rounded-2xl border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="flex flex-col gap-4 border-b border-white/20 pb-5 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent/10 text-accent">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">AI Coach Analysis</h2>
              <p className="mt-1 text-sm text-muted">
                {insight ? `Generated ${formatRelativeTime(insight.generated_at)}` : "Targeted rep coaching guidance"}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Refresh AI coach analysis"
            onClick={() => void loadInsight()}
            disabled={insightLoading}
            className="inline-flex items-center gap-2 self-start rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm font-medium text-ink transition hover:bg-white/80 disabled:opacity-60"
          >
            <RefreshCcw className={`h-4 w-4 ${insightLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        <div className="mt-6">
          {insightLoading && !insight ? <InsightSkeleton /> : null}

          {!insightLoading && !insight && insightError ? (
            <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-5 py-6">
              <p className="text-sm font-medium text-error">Could not generate analysis. Try refreshing.</p>
              <button
                type="button"
                aria-label="Retry AI coach analysis"
                onClick={() => void loadInsight()}
                className="mt-4 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover"
              >
                <RefreshCcw className="h-4 w-4" />
                Retry
              </button>
            </div>
          ) : null}

          {insight ? (
            <div className="space-y-6">
              {insightLoading ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900">
                  Refreshing AI coach analysis...
                </div>
              ) : null}

              {!insightLoading && insightError ? (
                <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-5 py-4 text-sm text-error">
                  {insightError}
                </div>
              ) : null}

              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Diagnosis</div>
                <p className="mt-3 text-2xl font-black tracking-tight text-ink">{insight.headline}</p>
                <AiMetaStrip meta={insight.ai_meta} />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-2xl border border-white/25 bg-white/50 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Primary Weakness</div>
                  <p className="mt-3 text-lg font-semibold text-ink">{insight.primary_weakness}</p>
                </div>
                <div className="rounded-2xl border border-white/25 bg-white/50 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Root Cause</div>
                  <p className="mt-3 text-sm leading-6 text-ink">{insight.root_cause}</p>
                </div>
              </div>

              <div className="rounded-2xl border border-white/25 bg-white/50 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Next Drill</div>
                    <p className="mt-3 text-sm font-medium leading-6 text-ink">{insight.drill_recommendation}</p>
                  </div>
                  <button
                    type="button"
                    aria-label="Assign recommended drill"
                    onClick={() =>
                      navigate("/manager/assignments/new", {
                        state: {
                          prefillScenarioSearch: drillPrefill?.scenarioSearch ?? insight.drill_recommendation,
                          prefillDifficulty: drillPrefill?.difficulty,
                          prefillRepIds: [repId],
                        },
                      })
                    }
                    className="inline-flex shrink-0 items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover"
                  >
                    Assign Drill
                    <ArrowRight className="h-4 w-4" />
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-white/25 bg-white/50 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Coaching Script</div>
                    <p className="mt-3 text-sm leading-6 text-ink">{insight.coaching_script}</p>
                  </div>
                  <button
                    type="button"
                    aria-label="Copy coaching script to clipboard"
                    onClick={() => void handleCopyScript()}
                    className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-white/35 bg-white/70 px-4 py-2 text-sm font-semibold text-ink transition hover:bg-white/90"
                  >
                    {copiedScript ? <Check className="h-4 w-4 text-accent" /> : <Copy className="h-4 w-4" />}
                    {copiedScript ? "Copied" : "Copy to clipboard"}
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-white/25 bg-white/50 p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Expected Outcome</div>
                <p className="mt-3 text-sm font-medium leading-6 text-ink">{insight.expected_improvement}</p>
              </div>
            </div>
          ) : null}
        </div>
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="flex flex-col overflow-hidden rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <h2 className="mb-4 text-base font-semibold text-ink">Session History</h2>

        {sessionRows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-white/20">
                  <th className="px-2 py-3 text-xs font-semibold uppercase tracking-wide text-muted">Date</th>
                  <th className="px-2 py-3 text-xs font-semibold uppercase tracking-wide text-muted">Scenario</th>
                  <th className="px-2 py-3 text-xs font-semibold uppercase tracking-wide text-muted">Duration</th>
                  <th className="px-2 py-3 text-xs font-semibold uppercase tracking-wide text-muted">Score</th>
                  <th className="px-2 py-3 text-xs font-semibold uppercase tracking-wide text-muted">Δ Prev</th>
                  <th className="px-2 py-3 text-right text-xs font-semibold uppercase tracking-wide text-muted">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {sessionRows.map((session) => (
                  <tr key={session.session_id} className="transition-colors hover:bg-white/20">
                    <td className="px-2 py-3 text-sm text-ink">
                      {session.started_at
                        ? new Date(session.started_at).toLocaleDateString(undefined, {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                          })
                        : "--"}
                    </td>
                    <td className="px-2 py-3 text-sm text-ink">
                      {session.scenario_name ??
                        session.feed?.scenario_name ??
                        session.feed?.scenario_id ??
                        "Unknown scenario"}
                    </td>
                    <td className="px-2 py-3 text-sm text-muted">{formatDuration(session.feed?.duration_seconds)}</td>
                    <td className="px-2 py-3">
                      <ScoreChip score={session.overall_score} />
                    </td>
                    <td className="px-2 py-3 text-sm font-medium text-ink">
                      {typeof session.scoreDelta === "number"
                        ? `${session.scoreDelta >= 0 ? "+" : ""}${session.scoreDelta.toFixed(1)}`
                        : "--"}
                    </td>
                    <td className="px-2 py-3 text-right">
                      <button
                        type="button"
                        aria-label={`View replay for session ${session.session_id}`}
                        onClick={() => navigate(`/manager/sessions/${session.session_id}/replay`)}
                        className="text-sm font-medium text-accent hover:underline"
                      >
                        View Replay
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState variant="empty" message="No session history available." />
        )}
      </motion.section>

      <OneOnOnePrepCard
        open={prepOpen}
        onClose={() => setPrepOpen(false)}
        managerId={managerId}
        repId={repId}
        repName={repName}
      />
    </motion.main>
  );
}
