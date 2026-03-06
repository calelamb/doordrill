import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowUpRight, BellRing, Gauge, Radar, TrendingDown, TrendingUp, Users } from "lucide-react";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "../components/EChartSurface";
import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerBenchmarks, fetchManagerCommandCenter } from "../lib/api";
import type { AlertItem, BenchmarksResponse, CommandCenterResponse } from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
  { key: "90", label: "90 days" },
  { key: "custom", label: "Custom" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];

function formatPercent(value: number | null | undefined) {
  if (typeof value !== "number") return "--";
  return `${Math.round(value * 100)}%`;
}

function formatDelta(value: number | null | undefined) {
  if (typeof value !== "number") return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}

function severityTone(alert: AlertItem) {
  if (alert.severity === "high") return "border-error/15 bg-error/[0.06] text-error";
  if (alert.severity === "medium") return "border-amber-400/20 bg-amber-100/40 text-amber-900";
  return "border-accent/15 bg-accent-soft/35 text-accent";
}

export function AnalyticsPage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<PeriodKey>("30");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [data, setData] = useState<CommandCenterResponse | null>(null);
  const [benchmarks, setBenchmarks] = useState<BenchmarksResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      const options = {
        period,
        dateFrom: period === "custom" ? customStart : undefined,
        dateTo: period === "custom" ? customEnd : undefined,
      };
      const [commandCenter, benchmarkData] = await Promise.all([
        fetchManagerCommandCenter(managerId, options),
        fetchManagerBenchmarks(managerId, options),
      ]);
      setData(commandCenter);
      setBenchmarks(benchmarkData);
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load command center");
    } finally {
      setLoading(false);
    }
  }, [customEnd, customStart, managerId, navigate, period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const histogram = useMemo(
    () =>
      (data?.score_distribution_histogram ?? []).map((bucket) => ({
        ...bucket,
        fill: bucket.max <= 6 ? "#f8c7bf" : bucket.max <= 8 ? "#f6dfa5" : "#cde7d1",
      })),
    [data?.score_distribution_histogram]
  );

  const trend = useMemo(
    () => (data?.score_trend ?? []).map((point) => ({ ...point, score: point.average_score ?? 0 })),
    [data?.score_trend]
  );

  const scoreTrendOption = useMemo<EChartsOption>(() => ({
    backgroundColor: "transparent",
    animationDuration: 480,
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(252,248,242,0.96)",
      borderColor: "rgba(45,90,61,0.12)",
      textStyle: { color: "#1d2a20" },
    },
    grid: { top: 24, right: 18, bottom: 28, left: 28 },
    xAxis: {
      type: "category",
      data: trend.map((point) => point.date),
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
        type: "line",
        smooth: true,
        data: trend.map((point) => point.score),
        symbolSize: 8,
        lineStyle: { width: 3, color: "#2d5a3d" },
        areaStyle: { color: "rgba(45,90,61,0.14)" },
        itemStyle: { color: "#2d5a3d" },
        markLine: {
          symbol: "none",
          lineStyle: { type: "dashed", color: "#c6951f" },
          data: [
            { yAxis: 7, label: { formatter: "Pass", color: "#8b6710" } },
            ...(typeof benchmarks?.score_benchmarks.upper_quartile === "number"
              ? [{ yAxis: benchmarks.score_benchmarks.upper_quartile, label: { formatter: "UQ", color: "#2d5a3d" } }]
              : []),
          ],
        },
      },
    ],
  }), [benchmarks?.score_benchmarks.upper_quartile, trend]);

  const riskMatrixOption = useMemo<EChartsOption>(() => ({
    backgroundColor: "transparent",
    animationDuration: 420,
    tooltip: {
      trigger: "item",
      backgroundColor: "rgba(252,248,242,0.96)",
      borderColor: "rgba(45,90,61,0.12)",
      formatter: (params: any) => {
        const rep = params?.data as {
          rep_name: string;
          average_score: number;
          score_delta: number;
          volatility: number;
        } | undefined;
        if (!rep) return "";
        return `${rep.rep_name}<br/>Avg ${rep.average_score.toFixed(1)}<br/>Delta ${formatDelta(rep.score_delta)}<br/>Volatility ${rep.volatility.toFixed(1)}`;
      },
    },
    grid: { top: 20, right: 16, bottom: 24, left: 32 },
    xAxis: {
      type: "value",
      name: "Delta",
      nameTextStyle: { color: "#667066", fontSize: 11 },
      splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
      axisLabel: { color: "#667066", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 10,
      name: "Average",
      nameTextStyle: { color: "#667066", fontSize: 11 },
      splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
      axisLabel: { color: "#667066", fontSize: 11 },
    },
    series: [
      {
        type: "scatter",
        data: (data?.rep_risk_matrix ?? []).map((rep) => ({
          value: [rep.score_delta, rep.average_score, rep.risk_score],
          ...rep,
        })),
        symbolSize: (_value: unknown, params: any) =>
          12 + Math.max(0, Number(params?.data?.risk_score ?? 0) * 3),
        itemStyle: {
          color: (params: any) => {
            if (params?.data?.risk_level === "high") return "#b5331e";
            if (params?.data?.risk_level === "medium") return "#c6951f";
            return "#2d5a3d";
          },
          shadowBlur: 18,
          shadowColor: "rgba(20,20,20,0.12)",
        },
        markLine: {
          symbol: "none",
          lineStyle: { type: "dashed", color: "rgba(26,46,26,0.24)" },
          data: [{ xAxis: 0 }, { yAxis: 7 }],
        },
      },
    ],
  }), [data?.rep_risk_matrix]);

  const distributionOption = useMemo<EChartsOption>(() => ({
    backgroundColor: "transparent",
    animationDuration: 400,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
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
        type: "bar",
        data: histogram.map((entry) => ({
          value: entry.count,
          itemStyle: { color: entry.fill, borderRadius: [14, 14, 0, 0] },
        })),
        barWidth: "58%",
      },
    ],
  }), [histogram]);

  const scenarioHeatmapOption = useMemo<EChartsOption>(() => {
    const scenarioRows = data?.scenario_pass_matrix?.slice(0, 10) ?? [];
    const scenarioNames = scenarioRows.map((scenario) => scenario.scenario_name);
    return {
      backgroundColor: "transparent",
      animationDuration: 420,
      tooltip: {
        position: "top",
        formatter: (params: any) => {
          const [x, y, value] = (params?.data ?? []) as [number, number, number];
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
          data: scenarioRows.flatMap((scenario, index) => ([
            [index, 0, scenario.pass_rate * 10],
            [index, 1, scenario.average_score ?? 0],
            [index, 2, scenario.difficulty * 2],
          ])),
          label: {
            show: true,
            color: "#fff8f0",
            formatter: (params: any) => {
              const [, metricIndex, value] = (params?.data ?? []) as [number, number, number];
              return metricIndex === 0 ? `${Math.round(value * 10)}%` : value.toFixed(1);
            },
          },
        },
      ],
    } as EChartsOption;
  }, [data?.scenario_pass_matrix]);

  if (loading) return <EmptyState variant="loading" message="Loading command center..." />;
  if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  if (!data) return <EmptyState variant="empty" message="No command center data available." />;

  const summary = data.summary;

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6 space-y-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/55 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted">
            <Gauge className="h-3.5 w-3.5 text-accent" />
            DoorDrill Management
          </div>
          <h1 className="mt-4 text-3xl font-black tracking-tight text-ink">Command Center</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted">
            Team health, rep risk, scenario performance, and coaching signals linked back to session evidence.
          </p>
          {data?._meta?.analytics_last_refresh_at ? (
            <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/55 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
              Data fresh {data._meta.freshness_seconds ?? 0}s ago
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          <div className="flex flex-wrap rounded-2xl border border-white/35 bg-white/55 p-1 shadow-sm">
            {PERIOD_OPTIONS.map((option) => {
              const active = option.key === period;
              return (
                <button
                  key={option.key}
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
                type="date"
                value={customStart}
                onChange={(event) => setCustomStart(event.target.value)}
                className="rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/20"
              />
              <input
                type="date"
                value={customEnd}
                onChange={(event) => setCustomEnd(event.target.value)}
                className="rounded-xl border border-white/35 bg-white/60 px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/20"
              />
            </div>
          ) : null}
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
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
          { label: "Completion", value: formatPercent(summary.completion_rate), meta: `${summary.sessions_count} sessions`, icon: ArrowUpRight },
          { label: "Review Coverage", value: formatPercent(summary.review_coverage_rate), meta: `${summary.scored_session_count} scored`, icon: BellRing },
          { label: "Reps At Risk", value: String(summary.reps_at_risk), meta: `${summary.active_rep_count} active reps`, icon: AlertTriangle },
          { label: "Overdue Drills", value: String(summary.overdue_assignments), meta: "Needs manager action", icon: Users },
        ].map((card) => (
          <div key={card.label} className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
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
          </div>
        ))}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
        <div className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_left,rgba(45,90,61,0.18),transparent_42%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">Score Momentum</h2>
              <p className="mt-1 text-sm text-muted">Daily average team performance for the selected period.</p>
            </div>
            <div className="rounded-full border border-white/35 bg-white/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-muted">
              Median {benchmarks?.score_benchmarks.median?.toFixed(1) ?? "--"}
            </div>
          </div>
          {trend.length ? (
            <EChartSurface option={scoreTrendOption} height={340} />
          ) : (
            <EmptyState variant="empty" message="No score trend available yet." />
          )}
        </div>

        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-5 flex items-center gap-2">
            <BellRing className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Manager Alerts</h2>
          </div>
          <div className="space-y-3">
            {data.alerts_preview.length ? (
              data.alerts_preview.map((alert) => (
                <button
                  key={alert.id}
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
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <div className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_right,rgba(198,149,31,0.16),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-5 flex items-center gap-2">
            <Radar className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Rep Risk Matrix</h2>
          </div>
          {data.rep_risk_matrix.length ? (
            <>
              <EChartSurface option={riskMatrixOption} height={300} />
              <div className="mt-4 space-y-2">
                {data.rep_risk_matrix.slice(0, 5).map((rep) => (
                  <button
                    key={rep.rep_id}
                    onClick={() => {
                      if (rep.session_id) openReplay(rep.session_id, rep.focus_turn_id ?? null);
                      else navigate(`/manager/reps/${rep.rep_id}/progress`);
                    }}
                    className="flex w-full items-center justify-between rounded-2xl border border-white/25 bg-white/45 px-4 py-3 text-left transition hover:bg-white/65"
                  >
                    <div>
                      <div className="text-sm font-semibold text-ink">{rep.rep_name}</div>
                      <div className="mt-1 text-xs text-muted">Avg {rep.average_score.toFixed(1)} · Δ {formatDelta(rep.score_delta)} · volatility {rep.volatility.toFixed(1)}</div>
                    </div>
                    <span className="rounded-full bg-white/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink">
                      {rep.risk_level}
                    </span>
                  </button>
                ))}
              </div>
            </>
          ) : (
            <EmptyState variant="empty" message="No rep risk signals yet." />
          )}
        </div>

        <div className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_left,rgba(181,51,30,0.12),transparent_35%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">Score Distribution</h2>
              <p className="mt-1 text-sm text-muted">Where sessions are clustering across the scoring range.</p>
            </div>
            <button
              onClick={() => navigate("/manager/explorer")}
              className="rounded-full border border-white/35 bg-white/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/75"
            >
              Open Explorer
            </button>
          </div>
          {histogram.length ? (
            <EChartSurface option={distributionOption} height={340} />
          ) : (
            <EmptyState variant="empty" message="No scored sessions to plot yet." />
          )}
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="relative overflow-hidden rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_center,rgba(45,90,61,0.12),transparent_40%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-ink">Scenario Pressure Map</h2>
              <p className="mt-1 text-sm text-muted">Difficulty, pass rate, and average score side by side.</p>
            </div>
            <button
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
                    <div className="mt-1 text-xs text-muted">Difficulty {scenario.difficulty} · {scenario.session_count} sessions</div>
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
                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(6, scenario.pass_rate * 100)}%` }} />
                </div>
                {scenario.sample_session_id ? (
                  <button
                    onClick={() => openReplay(scenario.sample_session_id ?? null, scenario.focus_turn_id ?? null)}
                    className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
                  >
                    Open Evidence
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
            <h2 className="text-lg font-bold tracking-tight text-ink">Weakest Categories</h2>
            <div className="mt-4 space-y-3">
              {data.weakest_categories.length ? (
                data.weakest_categories.map((item) => (
                  <button
                    key={item.category}
                    onClick={() => openReplay(item.session_id ?? null, item.focus_turn_id ?? null, item.category)}
                    disabled={!item.session_id}
                    className="w-full text-left disabled:cursor-default"
                  >
                    <div className="mb-1 flex items-center justify-between text-sm">
                      <span className="font-semibold capitalize text-ink">{item.category.replace(/_/g, " ")}</span>
                      <span className="text-muted">{item.average_score.toFixed(1)}</span>
                    </div>
                    <div className="h-2 rounded-full bg-accent-soft">
                      <div className="h-full rounded-full bg-[linear-gradient(90deg,#b5331e_0%,#c6951f_52%,#2d5a3d_100%)]" style={{ width: `${Math.max(4, item.average_score * 10)}%` }} />
                    </div>
                  </button>
                ))
              ) : (
                <EmptyState variant="empty" message="No category averages yet." />
              )}
            </div>
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
                  <div className="mt-2 text-2xl font-black tracking-tight text-ink">{typeof item.value === "number" ? item.value.toFixed(1) : "--"}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </motion.main>
  );
}
