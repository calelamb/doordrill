import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Layers3, ShieldCheck } from "lucide-react";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "../components/EChartSurface";
import { ObjectionTreemap } from "../components/ObjectionTreemap";
import { ChartSkeleton } from "../components/shared/ChartSkeleton";
import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerScenarioIntelligence } from "../lib/api";
import { cardVariants, pageVariants } from "../lib/motion";
import type { ScenarioIntelligenceResponse } from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "7", label: "7D" },
  { key: "30", label: "30D" },
  { key: "90", label: "90D" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];
type ScatterPoint = ScenarioIntelligenceResponse["items"][number] & {
  x: number;
  y: number;
  z: number;
  value: [number, number, number];
};

function ScenarioIntelligenceSkeleton() {
  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.div variants={cardVariants} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-2">
          <ChartSkeleton heightClass="h-10" className="max-w-[260px]" />
          <ChartSkeleton heightClass="h-4" className="max-w-[420px]" />
        </div>
        <ChartSkeleton heightClass="h-12" className="w-full max-w-[220px]" />
      </motion.div>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <ChartSkeleton key={index} heightClass="h-32" className="rounded-[28px]" />
        ))}
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <ChartSkeleton key={index} heightClass="h-28" className="rounded-[28px]" />
        ))}
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <ChartSkeleton heightClass="h-[380px]" className="rounded-[32px]" />
        <ChartSkeleton heightClass="h-[380px]" className="rounded-[32px]" />
      </motion.section>

      <motion.section variants={cardVariants}>
        <ChartSkeleton heightClass="h-[420px]" className="rounded-[32px]" />
      </motion.section>
    </motion.main>
  );
}

export function ScenarioIntelligencePage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<PeriodKey>("30");
  const [data, setData] = useState<ScenarioIntelligenceResponse | null>(null);
  const [selectedObjectionTag, setSelectedObjectionTag] = useState<string | null>(null);
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
    } catch (loadError) {
      if (isAuthError(loadError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(loadError instanceof Error ? loadError.message : "Failed to load scenario intelligence");
    } finally {
      setLoading(false);
    }
  }, [managerId, navigate, period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const scatterData = useMemo<ScatterPoint[]>(
    () =>
      (data?.items ?? []).map((item) => ({
        ...item,
        x: item.difficulty,
        y: Math.round(item.pass_rate * 100),
        z: item.average_score ?? 0,
        value: [item.difficulty, Math.round(item.pass_rate * 100), item.average_score ?? 0],
      })),
    [data?.items]
  );

  const filteredScenarioIds = useMemo(() => {
    if (!selectedObjectionTag) {
      return null;
    }
    return new Set(
      (data?.objection_failure_map ?? [])
        .filter((item) => item.objection_tag === selectedObjectionTag)
        .map((item) => item.scenario_id)
    );
  }, [data?.objection_failure_map, selectedObjectionTag]);

  const filteredItems = useMemo(() => {
    if (!filteredScenarioIds) {
      return data?.items ?? [];
    }
    return (data?.items ?? []).filter((item) => filteredScenarioIds.has(item.scenario_id));
  }, [data?.items, filteredScenarioIds]);

  const difficultyOption = useMemo<EChartsOption>(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const item = (params as { data?: ScatterPoint }).data;
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
        data: scatterData,
        symbolSize: (_value: unknown, params: unknown) => {
          const item = (params as { data?: ScatterPoint }).data;
          return 18 + Math.max(0, (item?.z ?? 0) * 2);
        },
        itemStyle: { color: "#2d5a3d", shadowBlur: 18, shadowColor: "rgba(20,20,20,0.12)" },
      },
    ],
  }), [scatterData]);

  const strongestScenario = useMemo(() => {
    const items = [...(data?.items ?? [])].filter((item) => item.average_score !== null);
    items.sort((left, right) => (right.average_score ?? 0) - (left.average_score ?? 0));
    return items[0] ?? null;
  }, [data?.items]);

  const toughestScenario = useMemo(() => {
    const items = [...(data?.items ?? [])].filter((item) => item.average_score !== null);
    items.sort((left, right) => (left.pass_rate - right.pass_rate) || ((left.average_score ?? 0) - (right.average_score ?? 0)));
    return items[0] ?? null;
  }, [data?.items]);

  if (loading) return <ScenarioIntelligenceSkeleton />;
  if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  if (!data || !data.items.length) return <EmptyState variant="empty" message="No scenario intelligence available yet." />;

  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.header variants={cardVariants} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-3xl font-black tracking-tight text-ink">Scenario Intelligence</h1>
          <p className="mt-1 text-sm text-muted">
            Find which drills create durable skill, which stall reps, and where objections cluster.
          </p>
        </div>
        <div className="flex rounded-2xl border border-white/35 bg-white/55 p-1">
          {PERIOD_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              aria-label={`Show scenario intelligence for ${option.label}`}
              onClick={() => setPeriod(option.key)}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${period === option.key ? "bg-accent text-white" : "text-muted hover:bg-white/70 hover:text-ink"}`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </motion.header>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-3">
        <motion.div
          variants={cardVariants}
          className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Strongest Scenario</div>
          <div className="mt-3 text-xl font-bold text-ink">{strongestScenario?.scenario_name ?? "--"}</div>
          <div className="mt-2 text-sm text-muted">
            Avg {strongestScenario?.average_score?.toFixed(1) ?? "--"} · Pass {Math.round((strongestScenario?.pass_rate ?? 0) * 100)}%
          </div>
          {strongestScenario?.sample_session_id ? (
            <button
              type="button"
              aria-label={`Open evidence for ${strongestScenario.scenario_name}`}
              onClick={() => openReplay(strongestScenario.sample_session_id, strongestScenario.focus_turn_id)}
              className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
            >
              Open evidence
            </button>
          ) : null}
        </motion.div>
        <motion.div
          variants={cardVariants}
          className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Most Punishing</div>
          <div className="mt-3 text-xl font-bold text-ink">{toughestScenario?.scenario_name ?? "--"}</div>
          <div className="mt-2 text-sm text-muted">
            Difficulty {toughestScenario?.difficulty ?? "--"} · Pass {Math.round((toughestScenario?.pass_rate ?? 0) * 100)}%
          </div>
          {toughestScenario?.sample_session_id ? (
            <button
              type="button"
              aria-label={`Open evidence for ${toughestScenario.scenario_name}`}
              onClick={() => openReplay(toughestScenario.sample_session_id, toughestScenario.focus_turn_id)}
              className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
            >
              Open evidence
            </button>
          ) : null}
        </motion.div>
        <motion.div
          variants={cardVariants}
          className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Scenario Volume</div>
          <div className="mt-3 text-xl font-bold text-ink">{data.items.length}</div>
          <div className="mt-2 text-sm text-muted">Active scenarios in the selected window</div>
        </motion.div>
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {(data.difficulty_bands ?? []).map((band) => (
          <motion.div
            key={band.difficulty}
            variants={cardVariants}
            className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl"
          >
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
              Difficulty {band.difficulty}
            </div>
            <div className="mt-3 text-2xl font-black tracking-tight text-ink">{Math.round(band.pass_rate * 100)}%</div>
            <div className="mt-2 text-sm text-muted">
              Pass rate · avg {band.average_score?.toFixed(1) ?? "--"} · {band.session_count} sessions
            </div>
          </motion.div>
        ))}
      </motion.section>

      <motion.section variants={cardVariants} className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Difficulty vs Pass Rate</h2>
          </div>
          <EChartSurface option={difficultyOption} height={320} />
        </motion.div>

        <motion.div
          variants={cardVariants}
          className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
        >
          <div className="mb-4 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-accent" />
              <h2 className="text-lg font-bold tracking-tight text-ink">Objection Failure Clusters</h2>
            </div>
            {selectedObjectionTag ? (
              <button
                type="button"
                aria-label="Clear objection filter"
                onClick={() => setSelectedObjectionTag(null)}
                className="rounded-full border border-white/35 bg-white/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/75"
              >
                Clear filter
              </button>
            ) : null}
          </div>
          <ObjectionTreemap
            items={data.objection_failure_map}
            scenarios={data.items}
            selectedTag={selectedObjectionTag}
            onSelectTag={setSelectedObjectionTag}
          />
        </motion.div>
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Layers3 className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Scenario Leaderboard</h2>
          </div>
          {selectedObjectionTag ? (
            <div className="rounded-full border border-accent/20 bg-accent-soft/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
              Filtered by {selectedObjectionTag.replace(/[_-]/g, " ")}
            </div>
          ) : null}
        </div>
        <div className="grid gap-3">
          {filteredItems.length ? (
            filteredItems.map((scenario) => (
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
                      <div className="mt-1 font-bold text-ink">
                        {scenario.average_duration_seconds ? `${Math.round(scenario.average_duration_seconds / 60)}m` : "--"}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Repeat Δ</div>
                      <div className="mt-1 font-bold text-ink">
                        {typeof scenario.improvement_delta === "number"
                          ? `${scenario.improvement_delta >= 0 ? "+" : ""}${scenario.improvement_delta.toFixed(1)}`
                          : "--"}
                      </div>
                    </div>
                  </div>
                </div>
                {scenario.sample_session_id ? (
                  <button
                    type="button"
                    aria-label={`Replay evidence for ${scenario.scenario_name}`}
                    onClick={() => openReplay(scenario.sample_session_id, scenario.focus_turn_id)}
                    className="mt-3 rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
                  >
                    Replay evidence
                  </button>
                ) : null}
              </div>
            ))
          ) : (
            <EmptyState variant="empty" message="No scenarios match the selected objection filter." />
          )}
        </div>
      </motion.section>
    </motion.main>
  );
}
