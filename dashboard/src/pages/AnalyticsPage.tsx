import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { createColumnHelper, type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangle,
  ArrowUpRight,
  BellRing,
  Clock3,
  Database,
  Gauge,
  Layers3,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "../components/EChartSurface";
import { RepRiskQuadrant } from "../components/RepRiskQuadrant";
import { TeamSkillHeatmap } from "../components/TeamSkillHeatmap";
import { DataTable } from "../components/shared/DataTable";
import { EmptyState } from "../components/shared/EmptyState";
import { ChartSkeleton } from "../components/shared/ChartSkeleton";
import { ScoreChip } from "../components/shared/ScoreChip";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import {
  fetchAnalyticsMetricDefinitions,
  fetchManagerAnalytics,
  fetchManagerAnalyticsOperations,
  fetchManagerBenchmarks,
  fetchManagerCommandCenter,
} from "../lib/api";
import { PASSING_SCORE } from "../lib/analytics";
import { cardVariants, pageVariants } from "../lib/motion";
import { resolvePeriodWindow, type DashboardPeriodKey } from "../lib/periods";
import type {
  AlertItem,
  AnalyticsMetricDefinition,
  BenchmarksResponse,
  CommandCenterResponse,
  ManagerAnalytics,
  ManagerAnalyticsOperations,
} from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
  { key: "custom", label: "Custom" },
] as const satisfies ReadonlyArray<{ key: DashboardPeriodKey; label: string }>;

type CompletionRateRow = NonNullable<ManagerAnalytics["completion_rate_by_rep"]>[number];
type ScenarioPassRow = NonNullable<ManagerAnalytics["scenario_pass_rates"]>[number];

type AxisSeriesParam = {
  dataIndex?: number;
};

type HeatmapTooltipParam = {
  data?: [number, number, number];
};

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number") return "--";
  return `${Math.round(value * 100)}%`;
}

function formatDelta(value: number | null | undefined): string {
  if (typeof value !== "number") return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}

function formatTrendLabel(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function severityTone(alert: AlertItem): string {
  if (alert.severity === "high") return "border-error/15 bg-error/[0.06] text-error";
  if (alert.severity === "medium") return "border-amber-400/20 bg-amber-100/40 text-amber-900";
  return "border-accent/15 bg-accent-soft/35 text-accent";
}

function bucketColor(min: number, max: number): string {
  if (max <= 6.0) {
    return "#e7afa9";
  }
  if (min >= 7.5) {
    return "#b8d5be";
  }
  return "#f2d49b";
}

function AnalyticsPageSkeleton() {
  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.div variants={cardVariants} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-3">
          <ChartSkeleton heightClass="h-6" className="max-w-[180px]" />
          <ChartSkeleton heightClass="h-10" className="max-w-[280px]" />
          <ChartSkeleton heightClass="h-4" className="max-w-[520px]" />
        </div>
        <ChartSkeleton heightClass="h-14" className="w-full max-w-[320px]" />
      </motion.div>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <ChartSkeleton key={index} heightClass="h-32" className="rounded-[28px]" />
        ))}
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
        <ChartSkeleton heightClass="h-[380px]" className="rounded-[32px]" />
        <ChartSkeleton heightClass="h-[380px]" className="rounded-[32px]" />
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <ChartSkeleton heightClass="h-[420px]" className="rounded-[32px]" />
        <ChartSkeleton heightClass="h-[420px]" className="rounded-[32px]" />
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <ChartSkeleton heightClass="h-[420px]" className="rounded-[32px]" />
        <ChartSkeleton heightClass="h-[420px]" className="rounded-[32px]" />
      </motion.section>
    </motion.main>
  );
}

export function AnalyticsPage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<DashboardPeriodKey>("30");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [previousData, setPreviousData] = useState<CommandCenterResponse | null>(null);
  const [teamAnalytics, setTeamAnalytics] = useState<ManagerAnalytics | null>(null);
  const [benchmarks, setBenchmarks] = useState<BenchmarksResponse | null>(null);
  const [operations, setOperations] = useState<ManagerAnalyticsOperations | null>(null);
  const [metricDefinitions, setMetricDefinitions] = useState<AnalyticsMetricDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const periodWindow = useMemo(
    () => resolvePeriodWindow(period, customStart || undefined, customEnd || undefined),
    [customEnd, customStart, period]
  );

  function openReplay(sessionId?: string | null, turnId?: string | null, category?: string | null) {
    if (!sessionId) {
      return;
    }
    const params = new URLSearchParams();
    if (turnId) params.set("turnId", turnId);
    if (category) params.set("category", category);
    navigate(`/manager/sessions/${sessionId}/replay${params.toString() ? `?${params.toString()}` : ""}`);
  }

  const loadData = useCallback(async () => {
    if (!managerId) return;

    setLoading(true);
    setError(null);

    try {
      const currentOptions = {
        period: "custom",
        dateFrom: periodWindow.current.startInput,
        dateTo: periodWindow.current.endInput,
      };
      const previousOptions = {
        period: "custom",
        dateFrom: periodWindow.previous.startInput,
        dateTo: periodWindow.previous.endInput,
      };

      const [
        commandCenter,
        previousCommandCenter,
        benchmarkData,
        teamAnalyticsData,
        operationsData,
        definitionsData,
      ] = await Promise.all([
        fetchManagerCommandCenter(managerId, currentOptions),
        fetchManagerCommandCenter(managerId, previousOptions),
        fetchManagerBenchmarks(managerId, currentOptions),
        fetchManagerAnalytics(managerId, currentOptions),
        fetchManagerAnalyticsOperations(managerId),
        fetchAnalyticsMetricDefinitions(managerId),
      ]);

      setData(commandCenter);
      setPreviousData(previousCommandCenter);
      setBenchmarks(benchmarkData);
      setTeamAnalytics(teamAnalyticsData);
      setOperations(operationsData);
      setMetricDefinitions(definitionsData);
    } catch (loadError) {
      if (isAuthError(loadError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(loadError instanceof Error ? loadError.message : "Failed to load command center");
    } finally {
      setLoading(false);
    }
  }, [managerId, navigate, periodWindow.current.endInput, periodWindow.current.startInput, periodWindow.previous.endInput, periodWindow.previous.startInput]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const trendComparison = useMemo(() => {
    const previousTrend = previousData?.score_trend ?? [];
    return (data?.score_trend ?? []).map((point, index) => {
      const previousPoint = previousTrend[index] ?? null;
      const currentScore = point.average_score ?? null;
      const previousScore = previousPoint?.average_score ?? null;
      const delta =
        typeof currentScore === "number" && typeof previousScore === "number"
          ? Number((currentScore - previousScore).toFixed(2))
          : null;

      return {
        label: formatTrendLabel(point.date),
        date: point.date,
        sessionCount: point.session_count,
        score: currentScore,
        previousScore,
        delta,
      };
    });
  }, [data?.score_trend, previousData?.score_trend]);

  const histogram = useMemo(() => {
    const buckets = data?.score_distribution_histogram ?? [];
    const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
    return buckets.map((bucket) => ({
      ...bucket,
      midpoint: Number(((bucket.min + Math.min(bucket.max, 10)) / 2).toFixed(2)),
      percentage: total > 0 ? bucket.count / total : 0,
      fill: bucketColor(bucket.min, bucket.max),
    }));
  }, [data?.score_distribution_histogram]);

  const distributionCurve = useMemo(() => {
    if (!histogram.length) {
      return [];
    }

    const total = histogram.reduce((sum, bucket) => sum + bucket.count, 0);
    if (!total) {
      return histogram.map(() => 0);
    }

    const mean =
      histogram.reduce((sum, bucket) => sum + bucket.midpoint * bucket.count, 0) / total;
    const variance =
      histogram.reduce((sum, bucket) => sum + ((bucket.midpoint - mean) ** 2) * bucket.count, 0) / total;
    const sigma = Math.max(0.5, Math.sqrt(variance));
    const bucketWidth = Math.max(0.5, histogram[0]?.max - histogram[0]?.min);

    return histogram.map((bucket) => {
      const exponent = -(((bucket.midpoint - mean) ** 2) / (2 * sigma ** 2));
      const density = Math.exp(exponent) / (sigma * Math.sqrt(2 * Math.PI));
      return Number((density * total * bucketWidth).toFixed(2));
    });
  }, [histogram]);

  const repPerformanceBuckets = useMemo(() => {
    const buckets = { atRisk: 0, onTarget: 0, exceeding: 0 };
    for (const rep of data?.rep_risk_matrix ?? []) {
      if (rep.average_score < 6.0) {
        buckets.atRisk += 1;
      } else if (rep.average_score <= 7.5) {
        buckets.onTarget += 1;
      } else {
        buckets.exceeding += 1;
      }
    }
    return buckets;
  }, [data?.rep_risk_matrix]);

  const scoreTrendOption = useMemo<EChartsOption>(() => {
    const lowerQuartile = benchmarks?.score_benchmarks.lower_quartile ?? null;
    const upperQuartile = benchmarks?.score_benchmarks.upper_quartile ?? null;

    return {
      backgroundColor: "transparent",
      animationDuration: 1200,
      animationEasing: "cubicOut",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross", lineStyle: { color: "rgba(45,90,61,0.2)" } },
        backgroundColor: "rgba(252,248,242,0.96)",
        borderColor: "rgba(45,90,61,0.12)",
        textStyle: { color: "#1d2a20" },
        formatter: (params: unknown) => {
          const seriesParams = Array.isArray(params) ? (params as AxisSeriesParam[]) : [];
          const index = seriesParams[0]?.dataIndex ?? 0;
          const point = trendComparison[index];
          if (!point) {
            return "";
          }
          return [
            `<strong>${new Date(point.date).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}</strong>`,
            `${point.sessionCount} sessions`,
            `Average score: ${typeof point.score === "number" ? point.score.toFixed(1) : "--"}`,
            `Delta vs previous: ${formatDelta(point.delta)}`,
          ].join("<br/>");
        },
      },
      grid: { top: 26, right: 18, bottom: 28, left: 28 },
      xAxis: {
        type: "category",
        data: trendComparison.map((point) => point.label),
        axisLine: { lineStyle: { color: "rgba(29,42,32,0.12)" } },
        axisLabel: { color: "#667066", fontSize: 11 },
        axisTick: { show: false },
        boundaryGap: false,
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 10,
        splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
        axisLabel: { color: "#667066", fontSize: 11 },
      },
      series: [
        {
          name: "Previous period",
          type: "line",
          smooth: true,
          showSymbol: false,
          data: trendComparison.map((point) => point.previousScore),
          lineStyle: { width: 2, color: "rgba(90,110,90,0.55)", type: "dashed" },
          itemStyle: { color: "rgba(90,110,90,0.55)" },
        },
        {
          name: "Lower quartile",
          type: "line",
          smooth: true,
          showSymbol: false,
          silent: true,
          data: trendComparison.map(() => lowerQuartile),
          lineStyle: { width: 1, color: "rgba(45,90,61,0.16)" },
          itemStyle: { color: "rgba(45,90,61,0.16)" },
        },
        {
          name: "Upper quartile",
          type: "line",
          smooth: true,
          showSymbol: false,
          silent: true,
          data: trendComparison.map(() => upperQuartile),
          lineStyle: { width: 1, color: "rgba(45,90,61,0.16)" },
          itemStyle: { color: "rgba(45,90,61,0.16)" },
        },
        {
          name: "Team trend",
          type: "line",
          smooth: true,
          data: trendComparison.map((point) => point.score),
          symbolSize: 8,
          lineStyle: { width: 3, color: "#2d5a3d" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(45,90,61,0.4)" },
                { offset: 1, color: "rgba(45,90,61,0)" },
              ],
            },
          },
          itemStyle: { color: "#2d5a3d" },
          markArea:
            typeof lowerQuartile === "number" && typeof upperQuartile === "number"
              ? {
                  silent: true,
                  itemStyle: { color: "rgba(45,90,61,0.08)" },
                  data: [[{ yAxis: lowerQuartile }, { yAxis: upperQuartile }]],
                }
              : undefined,
          markLine: {
            symbol: "none",
            lineStyle: { type: "dashed", color: "#c6951f" },
            data: [{ yAxis: PASSING_SCORE, label: { formatter: "Pass", color: "#8b6710" } }],
          },
        },
      ],
    };
  }, [benchmarks?.score_benchmarks.lower_quartile, benchmarks?.score_benchmarks.upper_quartile, trendComparison]);

  const distributionOption = useMemo<EChartsOption>(() => {
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: unknown) => {
          const items = Array.isArray(params) ? (params as Array<{ dataIndex?: number }>) : [];
          const index = items[0]?.dataIndex ?? 0;
          const bucket = histogram[index];
          if (!bucket) {
            return "";
          }
          return `${bucket.count} sessions scored ${bucket.min.toFixed(1)}-${Math.min(bucket.max, 10).toFixed(1)} — ${Math.round(bucket.percentage * 100)}% of total`;
        },
      },
      grid: { top: 20, right: 16, bottom: 24, left: 24 },
      xAxis: {
        type: "category",
        data: histogram.map((entry) => entry.label),
        axisLabel: { color: "#667066", fontSize: 11 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "rgba(29,42,32,0.12)" } },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#667066", fontSize: 11 },
        splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
      },
      series: [
        {
          name: "Score buckets",
          type: "bar",
          data: histogram.map((entry) => ({
            value: entry.count,
            itemStyle: { color: entry.fill, borderRadius: [14, 14, 0, 0] },
          })),
          barWidth: "58%",
          animationDuration: 700,
          animationDelay: (index: number) => index * 80,
        },
        {
          name: "Ideal distribution",
          type: "line",
          data: distributionCurve,
          smooth: true,
          symbol: "none",
          lineStyle: { width: 2, color: "rgba(90,110,90,0.7)", type: "dashed" },
        },
      ],
    };
  }, [distributionCurve, histogram]);

  const scenarioHeatmapOption = useMemo<EChartsOption>(() => {
    const scenarioRows = data?.scenario_pass_matrix?.slice(0, 10) ?? [];
    const scenarioNames = scenarioRows.map((scenario) => scenario.scenario_name);

    return {
      backgroundColor: "transparent",
      animationDuration: 420,
      tooltip: {
        position: "top",
        formatter: (params: unknown) => {
          const cell = (params as HeatmapTooltipParam).data ?? [0, 0, 0];
          const [x, y, value] = cell;
          const metric = ["Pass Rate", "Avg Score", "Difficulty"][y] ?? "Metric";
          const label = scenarioNames[x] ?? "Scenario";
          const formatted = y === 0 ? `${Math.round(value * 10)}%` : value.toFixed(1);
          return `${label}<br/>${metric}: ${formatted}`;
        },
      },
      grid: { top: 18, right: 16, bottom: 60, left: 92 },
      xAxis: {
        type: "category",
        data: scenarioNames,
        axisLabel: { color: "#667066", fontSize: 11, interval: 0, rotate: 18 },
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        data: ["Pass Rate", "Avg Score", "Difficulty"],
        axisLabel: { color: "#667066", fontSize: 11 },
      },
      visualMap: {
        min: 0,
        max: 10,
        orient: "horizontal",
        left: "center",
        bottom: 8,
        calculable: false,
        textStyle: { color: "#667066", fontSize: 11 },
        inRange: { color: ["#b5331e", "#c6951f", "#2d5a3d"] },
      },
      series: [
        {
          type: "heatmap",
          data: scenarioRows.flatMap((scenario, index) => [
            [index, 0, scenario.pass_rate * 10],
            [index, 1, scenario.average_score ?? 0],
            [index, 2, scenario.difficulty * 2],
          ]),
          label: {
            show: true,
            color: "#fff8f0",
            formatter: (params: unknown) => {
              const cell = (params as HeatmapTooltipParam).data ?? [0, 0, 0];
              const metricIndex = cell[1];
              const value = cell[2];
              return metricIndex === 0 ? `${Math.round(value * 10)}%` : value.toFixed(1);
            },
          },
        },
      ],
    };
  }, [data?.scenario_pass_matrix]);

  const repCompletionColumns = useMemo<Array<ColumnDef<CompletionRateRow>>>(() => {
    const columnHelper = createColumnHelper<CompletionRateRow>();
    return [
      columnHelper.accessor("rep_name", {
        header: "Rep",
        cell: (info) => (
          <button
            type="button"
            onClick={() => navigate(`/manager/reps/${info.row.original.rep_id}/progress`)}
            className="font-semibold text-ink transition hover:text-accent"
          >
            {info.getValue()}
          </button>
        ),
      }),
      columnHelper.accessor("completed_assignment_count", {
        header: "Done",
        cell: (info) => String(info.getValue()),
      }),
      columnHelper.accessor("assignment_count", {
        header: "Assigned",
        cell: (info) => String(info.getValue()),
      }),
      columnHelper.accessor("completion_rate", {
        header: "Completion",
        cell: (info) => formatPercent(info.getValue()),
      }),
    ] as Array<ColumnDef<CompletionRateRow>>;
  }, [navigate]);

  const scenarioPassColumns = useMemo<Array<ColumnDef<ScenarioPassRow>>>(() => {
    const columnHelper = createColumnHelper<ScenarioPassRow>();
    return [
      columnHelper.accessor("scenario_name", {
        header: "Scenario",
      }),
      columnHelper.accessor("pass_rate", {
        header: "Pass",
        cell: (info) => formatPercent(info.getValue()),
      }),
      columnHelper.accessor("pass_count", {
        header: "Passes",
        cell: (info) => String(info.getValue()),
      }),
      columnHelper.accessor("scored_session_count", {
        header: "Samples",
        cell: (info) => String(info.getValue()),
      }),
    ] as Array<ColumnDef<ScenarioPassRow>>;
  }, []);

  const metricDefinitionColumns = useMemo<Array<ColumnDef<AnalyticsMetricDefinition>>>(() => {
    const columnHelper = createColumnHelper<AnalyticsMetricDefinition>();
    return [
      columnHelper.accessor("display_name", {
        header: "Metric",
        cell: (info) => (
          <div>
            <div className="font-semibold text-ink">{info.getValue()}</div>
            <div className="mt-1 text-xs leading-5 text-muted">{info.row.original.description}</div>
          </div>
        ),
      }),
      columnHelper.accessor("entity_type", {
        header: "Entity",
        cell: (info) => <span className="uppercase tracking-[0.16em] text-muted">{info.getValue()}</span>,
      }),
      columnHelper.accessor("aggregation_method", {
        header: "Method",
      }),
      columnHelper.accessor("owner", {
        header: "Owner",
      }),
    ] as Array<ColumnDef<AnalyticsMetricDefinition>>;
  }, []);

  if (loading) {
    return <AnalyticsPageSkeleton />;
  }

  if (error) {
    return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  }

  if (!data) {
    return <EmptyState variant="empty" message="No command center data available." />;
  }

  const summary = data.summary;
  const positiveMomentum =
    typeof summary.team_average_delta_vs_previous_period === "number" &&
    summary.team_average_delta_vs_previous_period >= 0;

  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.header variants={cardVariants} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/55 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted">
            <Gauge className="h-3.5 w-3.5 text-accent" />
            DoorDrill Management
          </div>
          <h1 className="mt-4 text-3xl font-black tracking-tight text-ink">Command Center</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted">
            Team health, rep risk, scenario performance, and coaching signals linked back to session evidence.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {data?._meta?.analytics_last_refresh_at ? (
              <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/55 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                <Clock3 className="h-3.5 w-3.5 text-accent" />
                Data fresh {data._meta.freshness_seconds ?? 0}s ago
              </div>
            ) : null}
            {data?._meta?.cache_status ? (
              <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/55 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                <Database className="h-3.5 w-3.5 text-accent" />
                Cache {data._meta.cache_status}
              </div>
            ) : null}
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex flex-wrap rounded-2xl border border-white/35 bg-white/55 p-1 shadow-sm">
            {PERIOD_OPTIONS.map((option) => {
              const active = option.key === period;
              return (
                <button
                  key={option.key}
                  type="button"
                  aria-label={`Show analytics for ${option.label}`}
                  onClick={() => setPeriod(option.key)}
                  className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${active ? "bg-accent text-white shadow-lg shadow-accent/20" : "text-muted hover:bg-white/70 hover:text-ink"}`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          {period === "custom" ? (
            <div className="flex gap-2">
              <input
                aria-label="Custom period start date"
                type="date"
                value={customStart}
                onChange={(event) => setCustomStart(event.target.value)}
                className="rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/20"
              />
              <input
                aria-label="Custom period end date"
                type="date"
                value={customEnd}
                onChange={(event) => setCustomEnd(event.target.value)}
                className="rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/20"
              />
            </div>
          ) : null}
        </div>
      </motion.header>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {[
          {
            label: "Team Average",
            value: summary.team_average_score?.toFixed(1) ?? "--",
            meta: `Δ ${formatDelta(summary.team_average_delta_vs_previous_period)}`,
            icon:
              summary.team_average_delta_vs_previous_period !== null &&
              summary.team_average_delta_vs_previous_period >= 0
                ? TrendingUp
                : TrendingDown,
          },
          {
            label: "Completion",
            value: formatPercent(summary.completion_rate),
            meta: `${summary.sessions_count} sessions`,
            icon: ArrowUpRight,
          },
          {
            label: "Review Coverage",
            value: formatPercent(summary.review_coverage_rate),
            meta: `${summary.scored_session_count} scored`,
            icon: BellRing,
          },
          {
            label: "Reps At Risk",
            value: String(summary.reps_at_risk),
            meta: `${summary.active_rep_count} active reps`,
            icon: AlertTriangle,
          },
          {
            label: "Overdue Drills",
            value: String(summary.overdue_assignments),
            meta: "Needs manager action",
            icon: Users,
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
                <div className="mt-2 text-sm text-muted">{card.meta}</div>
              </div>
              <div className="rounded-2xl bg-accent/10 p-3 text-accent">
                <card.icon className="h-5 w-5" />
              </div>
            </div>
          </motion.div>
        ))}
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
        <motion.div
          variants={cardVariants}
          className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_left,rgba(45,90,61,0.18),transparent_42%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">Score Momentum</h2>
              <p className="mt-1 text-sm text-muted">Daily average team performance for the selected period.</p>
            </div>
            <div className="flex items-center gap-3">
              <div
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${positiveMomentum ? "border-accent/20 bg-accent-soft/60 text-accent" : "border-red-200 bg-red-50/70 text-red-700"}`}
              >
                {positiveMomentum ? (
                  <TrendingUp className="h-3.5 w-3.5" />
                ) : (
                  <TrendingDown className="h-3.5 w-3.5" />
                )}
                {formatDelta(summary.team_average_delta_vs_previous_period)}
              </div>
              <div className="rounded-full border border-white/35 bg-white/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-muted">
                Median {benchmarks?.score_benchmarks.median?.toFixed(1) ?? "--"}
              </div>
            </div>
          </div>
          {trendComparison.length ? (
            <EChartSurface option={scoreTrendOption} height={340} />
          ) : (
            <EmptyState variant="empty" message="No score trend available yet." />
          )}
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-5 flex items-center gap-2">
            <BellRing className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Manager Alerts</h2>
          </div>
          <div className="space-y-3">
            {data.alerts_preview.length ? (
              data.alerts_preview.map((alert) => (
                <button
                  key={alert.id}
                  type="button"
                  aria-label={`Open alert ${alert.title}`}
                  onClick={() => {
                    if (alert.session_id) openReplay(alert.session_id, alert.focus_turn_id ?? null);
                    else if (alert.rep_id) navigate(`/manager/reps/${alert.rep_id}/progress`);
                  }}
                  className={`w-full rounded-2xl border px-4 py-4 text-left transition hover:translate-x-0.5 ${severityTone(alert)}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold">{alert.title}</div>
                      <p className="mt-1 text-sm leading-6 opacity-85">{alert.description}</p>
                    </div>
                    <span className="rounded-full bg-white/60 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]">
                      {alert.severity}
                    </span>
                  </div>
                </button>
              ))
            ) : (
              <EmptyState variant="empty" message="No active alerts in this period." />
            )}
          </div>
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <motion.div
          variants={cardVariants}
          className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_right,rgba(198,149,31,0.16),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-5 flex items-center gap-2">
            <Users className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Rep Risk Quadrant</h2>
          </div>
          <RepRiskQuadrant reps={data.rep_risk_matrix} />
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_left,rgba(181,51,30,0.12),transparent_35%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">Score Distribution</h2>
              <p className="mt-1 text-sm text-muted">Where sessions are clustering across the scoring range.</p>
            </div>
            <button
              type="button"
              aria-label="Open session explorer"
              onClick={() => navigate("/manager/explorer")}
              className="rounded-full border border-white/35 bg-white/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/75"
            >
              Open Explorer
            </button>
          </div>
          {histogram.length ? (
            <>
              <EChartSurface option={distributionOption} height={300} />
              <div className="mt-4 flex flex-wrap gap-3">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/60 px-3 py-2 text-sm text-ink">
                  <ScoreChip score={5.8} size="sm" />
                  {repPerformanceBuckets.atRisk} reps at risk (&lt; 6.0)
                </div>
                <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/60 px-3 py-2 text-sm text-ink">
                  <ScoreChip score={7.0} size="sm" />
                  {repPerformanceBuckets.onTarget} reps on target (6.0-7.5)
                </div>
                <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/60 px-3 py-2 text-sm text-ink">
                  <ScoreChip score={8.4} size="sm" />
                  {repPerformanceBuckets.exceeding} reps exceeding (&gt; 7.5)
                </div>
              </div>
            </>
          ) : (
            <EmptyState variant="empty" message="No scored sessions to plot yet." />
          )}
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <motion.div
          variants={cardVariants}
          className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_center,rgba(45,90,61,0.12),transparent_40%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">Scenario Pressure Map</h2>
              <p className="mt-1 text-sm text-muted">Difficulty, pass rate, and average score side by side.</p>
            </div>
            <button
              type="button"
              aria-label="Open scenario intelligence page"
              onClick={() => navigate("/manager/scenarios")}
              className="rounded-full border border-white/35 bg-white/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/75"
            >
              Scenario Lab
            </button>
          </div>
          {data.scenario_pass_matrix.length ? (
            <EChartSurface option={scenarioHeatmapOption} height={260} className="mb-5" />
          ) : null}
          <div className="space-y-3">
            {data.scenario_pass_matrix.slice(0, 8).map((scenario) => (
              <div key={scenario.scenario_id} className="rounded-2xl border border-white/25 bg-white/45 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <div className="text-sm font-semibold text-ink">{scenario.scenario_name}</div>
                    <div className="mt-1 text-xs text-muted">
                      Difficulty {scenario.difficulty} · {scenario.session_count} sessions
                    </div>
                  </div>
                  <div className="grid gap-3 text-right sm:grid-cols-3 sm:text-left md:text-right">
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Pass Rate</div>
                      <div className="text-base font-bold text-ink">{Math.round(scenario.pass_rate * 100)}%</div>
                    </div>
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Avg Score</div>
                      <div className="text-base font-bold text-ink">{scenario.average_score?.toFixed(1) ?? "--"}</div>
                    </div>
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Difficulty</div>
                      <div className="text-base font-bold text-ink">{scenario.difficulty}/5</div>
                    </div>
                  </div>
                </div>
                <div className="mt-3 h-2 rounded-full bg-accent-soft">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${Math.max(6, scenario.pass_rate * 100)}%` }}
                  />
                </div>
                {scenario.sample_session_id ? (
                  <button
                    type="button"
                    aria-label={`Open evidence for ${scenario.scenario_name}`}
                    onClick={() => openReplay(scenario.sample_session_id ?? null, scenario.focus_turn_id ?? null)}
                    className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
                  >
                    Open Evidence
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </motion.div>

        <motion.div variants={cardVariants} className="space-y-6">
          <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
            <div className="mb-4">
              <h2 className="text-lg font-bold tracking-tight text-ink">Team Skill Heatmap</h2>
              <p className="mt-1 text-sm text-muted">
                Drill into rep-by-category performance and jump straight into a focused progress view.
              </p>
            </div>
            <TeamSkillHeatmap
              managerId={managerId}
              reps={data.rep_risk_matrix}
              days={periodWindow.current.spanDays}
              dateFrom={periodWindow.current.startInput}
              dateTo={periodWindow.current.endInput}
            />
          </div>

          <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
            <h2 className="text-lg font-bold tracking-tight text-ink">Benchmark Band</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                { label: "Lower Quartile", value: benchmarks?.score_benchmarks.lower_quartile },
                { label: "Median", value: benchmarks?.score_benchmarks.median },
                { label: "Upper Quartile", value: benchmarks?.score_benchmarks.upper_quartile },
              ].map((item) => (
                <div key={item.label} className="rounded-2xl border border-white/25 bg-white/45 p-4 text-center">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{item.label}</div>
                  <div className="mt-2 text-2xl font-black tracking-tight text-ink">
                    {typeof item.value === "number" ? item.value.toFixed(1) : "--"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-4 flex items-center gap-2">
            <Users className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Completion By Rep</h2>
          </div>
          <DataTable
            columns={repCompletionColumns}
            data={teamAnalytics?.completion_rate_by_rep ?? []}
            emptyMessage="No assignment completion data in this window."
          />
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-4 flex items-center gap-2">
            <Layers3 className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Scenario Pass Leaderboard</h2>
          </div>
          <DataTable
            columns={scenarioPassColumns}
            data={teamAnalytics?.scenario_pass_rates ?? []}
            emptyMessage="No scenario pass-rate samples in this window."
          />
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_left,rgba(45,90,61,0.14),transparent_36%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-5 flex items-center gap-2">
            <Database className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Analytics Runtime</h2>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {[
              {
                label: "Last Refresh",
                value: operations?.analytics_last_refresh_at
                  ? new Date(operations.analytics_last_refresh_at).toLocaleString()
                  : "--",
              },
              {
                label: "Fact Sessions",
                value: String(operations?.warehouse.fact_session_count ?? 0),
              },
              {
                label: "Materialized Views",
                value: String(operations?.materialized_views.count ?? 0),
              },
              {
                label: "Refresh Failures",
                value: String(operations?.refresh_runs.failed_count ?? 0),
              },
            ].map((card) => (
              <div key={card.label} className="rounded-2xl border border-white/25 bg-white/50 p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{card.label}</div>
                <div className="mt-2 text-lg font-bold text-ink">{card.value}</div>
              </div>
            ))}
          </div>

          <div className="mt-5 grid gap-3 text-sm md:grid-cols-2">
            <div className="rounded-2xl border border-white/25 bg-white/45 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Cache</div>
              <div className="mt-2 text-ink">
                {operations?.cache.backend ?? "--"} · TTL {operations?.runtime.cache_ttl_seconds ?? 0}s
              </div>
              <div className="mt-1 text-xs text-muted">
                hits {operations?.cache.hits ?? 0} · misses {operations?.cache.misses ?? 0} · writes{" "}
                {operations?.cache.writes ?? 0}
              </div>
            </div>
            <div className="rounded-2xl border border-white/25 bg-white/45 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Latency Budget</div>
              <div className="mt-2 text-ink">
                warn {operations?.runtime.warn_ms ?? 0}ms · critical {operations?.runtime.critical_ms ?? 0}ms
              </div>
              <div className="mt-1 text-xs text-muted">
                partitions {operations?.partitions.count ?? 0} · active manager reps{" "}
                {operations?.warehouse.manager_rep_count ?? 0}
              </div>
            </div>
          </div>

          <div className="mt-5 space-y-3">
            {(operations?.refresh_runs.recent ?? []).slice(0, 5).map((run) => (
              <div key={run.id} className="rounded-2xl border border-white/25 bg-white/45 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-ink">
                      {run.scope_type} · {run.status}
                    </div>
                    <div className="mt-1 text-xs text-muted">
                      {run.started_at ? new Date(run.started_at).toLocaleString() : "--"}
                    </div>
                  </div>
                  <span className="rounded-full bg-white/65 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
                    {run.scope_id ? run.scope_id.slice(0, 12) : "global"}
                  </span>
                </div>
                {run.error ? <div className="mt-2 text-xs text-error">{run.error}</div> : null}
              </div>
            ))}
          </div>
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-4 flex items-center gap-2">
            <Gauge className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Metric Registry</h2>
          </div>
          <DataTable
            columns={metricDefinitionColumns}
            data={metricDefinitions}
            emptyMessage="No active metric definitions registered."
          />
        </motion.div>
      </motion.section>
    </motion.main>
  );
}
