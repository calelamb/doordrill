import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Layers3, ShieldCheck } from "lucide-react";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "../components/EChartSurface";
import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerScenarioIntelligence } from "../lib/api";
import type { ScenarioIntelligenceResponse } from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "7", label: "7D" },
  { key: "30", label: "30D" },
  { key: "90", label: "90D" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];

export function ScenarioIntelligencePage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<PeriodKey>("30");
  const [data, setData] = useState<ScenarioIntelligenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function openReplay(sessionId?: string | null, turnId?: string | null) {
    if (!sessionId) {
      return;
    }
    const params = new URLSearchParams();
    if (turnId) params.set("turnId", turnId);
    navigate(`/manager/sessions/${sessionId}/replay${params.toString() ? `?${params.toString()}` : ""}`);
  }

  const loadData = useCallback(async () => {
    if (!managerId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchManagerScenarioIntelligence(managerId, { period });
      setData(response);
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load scenario intelligence");
    } finally {
      setLoading(false);
    }
  }, [managerId, navigate, period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const scatterData = useMemo(
    () => (data?.items ?? []).map((item) => ({ ...item, x: item.difficulty, y: Math.round(item.pass_rate * 100), z: item.average_score ?? 0 })),
    [data?.items]
  );

  const objectionMap = useMemo(() => (data?.objection_failure_map ?? []).slice(0, 12), [data?.objection_failure_map]);

  const difficultyOption = useMemo<EChartsOption>(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: (params: any) => {
        const item = params?.data as { scenario_name: string; y: number; z: number } | undefined;
        if (!item) return "";
        return `${item.scenario_name}<br/>Pass ${item.y}%<br/>Avg ${item.z.toFixed(1)}`;
      },
    },
    grid: { top: 18, right: 18, bottom: 24, left: 28 },
    xAxis: {
      type: "value",
      min: 1,
      max: 5,
      name: "Difficulty",
      axisLabel: { color: "#667066", fontSize: 11 },
      splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      name: "Pass %",
      axisLabel: { color: "#667066", fontSize: 11 },
      splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
    },
    series: [
      {
        type: "scatter",
        data: scatterData.map((item) => ({
          value: [item.x, item.y, item.z],
          ...item,
        })),
        symbolSize: (_value: unknown, params: any) => 18 + Math.max(0, Number(params?.data?.z ?? 0) * 2),
        itemStyle: { color: "#2d5a3d", shadowBlur: 18, shadowColor: "rgba(20,20,20,0.12)" },
      },
    ],
  }), [scatterData]);

  const objectionOption = useMemo<EChartsOption>(() => ({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { top: 18, right: 18, bottom: 28, left: 100 },
    xAxis: {
      type: "value",
      axisLabel: { color: "#667066", fontSize: 11 },
      splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
    },
    yAxis: {
      type: "category",
      data: objectionMap.map((item) => item.objection_tag),
      axisLabel: { color: "#667066", fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        data: objectionMap.map((item, index) => ({
          value: item.count,
          itemStyle: {
            color: index % 2 === 0 ? "#2d5a3d" : "#b77a13",
            borderRadius: [0, 12, 12, 0],
          },
        })),
      },
    ],
  }), [objectionMap]);

  const strongestScenario = useMemo(() => {
    const items = [...(data?.items ?? [])].filter((item) => item.average_score !== null);
    items.sort((a, b) => (b.average_score ?? 0) - (a.average_score ?? 0));
    return items[0] ?? null;
  }, [data?.items]);

  const toughestScenario = useMemo(() => {
    const items = [...(data?.items ?? [])].filter((item) => item.average_score !== null);
    items.sort((a, b) => (a.pass_rate - b.pass_rate) || ((a.average_score ?? 0) - (b.average_score ?? 0)));
    return items[0] ?? null;
  }, [data?.items]);

  if (loading) return <EmptyState variant="loading" message="Loading scenario intelligence..." />;
  if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  if (!data || !data.items.length) return <EmptyState variant="empty" message="No scenario intelligence available yet." />;

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6 space-y-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-3xl font-black tracking-tight text-ink">Scenario Intelligence</h1>
          <p className="mt-1 text-sm text-muted">Find which drills create durable skill, which stall reps, and where objections cluster.</p>
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
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Strongest Scenario</div>
          <div className="mt-3 text-xl font-bold text-ink">{strongestScenario?.scenario_name ?? "--"}</div>
          <div className="mt-2 text-sm text-muted">Avg {strongestScenario?.average_score?.toFixed(1) ?? "--"} · Pass {(strongestScenario?.pass_rate ?? 0) * 100}%</div>
          {strongestScenario?.sample_session_id ? (
            <button
              onClick={() => openReplay(strongestScenario.sample_session_id, strongestScenario.focus_turn_id)}
              className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
            >
              Open evidence
            </button>
          ) : null}
        </div>
        <div className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Most Punishing</div>
          <div className="mt-3 text-xl font-bold text-ink">{toughestScenario?.scenario_name ?? "--"}</div>
          <div className="mt-2 text-sm text-muted">Difficulty {toughestScenario?.difficulty ?? "--"} · Pass {Math.round((toughestScenario?.pass_rate ?? 0) * 100)}%</div>
          {toughestScenario?.sample_session_id ? (
            <button
              onClick={() => openReplay(toughestScenario.sample_session_id, toughestScenario.focus_turn_id)}
              className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
            >
              Open evidence
            </button>
          ) : null}
        </div>
        <div className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Scenario Volume</div>
          <div className="mt-3 text-xl font-bold text-ink">{data.items.length}</div>
          <div className="mt-2 text-sm text-muted">Active scenarios in the selected window</div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Difficulty vs Pass Rate</h2>
          </div>
          <EChartSurface option={difficultyOption} height={320} />
        </div>

        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-4 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Objection Failure Clusters</h2>
          </div>
          <EChartSurface option={objectionOption} height={320} />
        </div>
      </section>

      <section className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
        <div className="mb-4 flex items-center gap-2">
          <Layers3 className="h-4 w-4 text-accent" />
          <h2 className="text-lg font-bold tracking-tight text-ink">Scenario Leaderboard</h2>
        </div>
        <div className="grid gap-3">
          {data.items.map((scenario) => (
            <div key={scenario.scenario_id} className="rounded-2xl border border-white/25 bg-white/45 p-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{scenario.scenario_name}</span>
                    <span className="rounded-full bg-white/60 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
                      difficulty {scenario.difficulty}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {scenario.top_weakness_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent">
                        {tag}
                      </span>
                    ))}
                    {scenario.top_objection_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-900">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="grid gap-3 text-sm sm:grid-cols-5">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Avg</div>
                    <div className="mt-1 font-bold text-ink">{scenario.average_score?.toFixed(1) ?? "--"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Pass</div>
                    <div className="mt-1 font-bold text-ink">{Math.round(scenario.pass_rate * 100)}%</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Reps</div>
                    <div className="mt-1 font-bold text-ink">{scenario.rep_count}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Duration</div>
                    <div className="mt-1 font-bold text-ink">{scenario.average_duration_seconds ? `${Math.round(scenario.average_duration_seconds / 60)}m` : "--"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Repeat Δ</div>
                    <div className="mt-1 font-bold text-ink">{typeof scenario.improvement_delta === "number" ? `${scenario.improvement_delta >= 0 ? "+" : ""}${scenario.improvement_delta.toFixed(1)}` : "--"}</div>
                  </div>
                </div>
              </div>
              {scenario.sample_session_id ? (
                <button
                  onClick={() => openReplay(scenario.sample_session_id, scenario.focus_turn_id)}
                  className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
                >
                  Replay evidence
                </button>
              ) : null}
            </div>
          ))}
        </div>
      </section>
    </motion.main>
  );
}
