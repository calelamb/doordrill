import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "./EChartSurface";
import { ChartSkeleton } from "./shared/ChartSkeleton";
import { EmptyState } from "./shared/EmptyState";
import { fetchRepProgress } from "../lib/api";
import {
  CATEGORY_META,
  PASSING_SCORE,
  getCategoryScore,
  type AnalyticsCategoryKey,
} from "../lib/analytics";
import type { CommandCenterResponse, RepProgress } from "../lib/types";

type TeamSkillHeatmapProps = {
  managerId: string;
  reps: CommandCenterResponse["rep_risk_matrix"];
  days: number;
  dateFrom?: string;
  dateTo?: string;
};

type HeatmapRow = {
  repId: string;
  repName: string;
  belowBenchmarkSessions: number;
  scores: Record<AnalyticsCategoryKey, number>;
};

type HeatmapCell = {
  value: [number, number, number];
  repId: string;
  repName: string;
  category: AnalyticsCategoryKey;
  belowBenchmarkSessions: number;
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function hexToRgb(hex: string): [number, number, number] {
  const normalized = hex.replace("#", "");
  const value = Number.parseInt(normalized, 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function mixChannel(start: number, end: number, weight: number): number {
  return Math.round(start + (end - start) * weight);
}

function interpolateColor(startHex: string, endHex: string, weight: number): string {
  const [startRed, startGreen, startBlue] = hexToRgb(startHex);
  const [endRed, endGreen, endBlue] = hexToRgb(endHex);
  const t = clamp(weight, 0, 1);
  const red = mixChannel(startRed, endRed, t);
  const green = mixChannel(startGreen, endGreen, t);
  const blue = mixChannel(startBlue, endBlue, t);
  return `rgb(${red}, ${green}, ${blue})`;
}

function scoreColor(score: number): string {
  if (score <= 5.0) {
    return "#dc2626";
  }
  if (score <= 6.5) {
    return interpolateColor("#dc2626", "#f59e0b", (score - 5.0) / 1.5);
  }
  if (score >= 8.5) {
    return "#2D5A3D";
  }
  return interpolateColor("#f59e0b", "#2D5A3D", (score - 6.5) / 2.0);
}

function getHeatmapScore(progress: RepProgress, category: AnalyticsCategoryKey): number {
  const value = getCategoryScore(progress.current_period_category_averages, category);
  return Number((value ?? 0).toFixed(2));
}

function buildHeatmapRows(reps: CommandCenterResponse["rep_risk_matrix"], progressRows: RepProgress[]): HeatmapRow[] {
  return reps.map((rep, index) => {
    const progress = progressRows[index];
    const belowBenchmarkSessions = (progress.trend ?? []).filter(
      (session) => typeof session.overall_score === "number" && session.overall_score < PASSING_SCORE
    ).length;

    return {
      repId: rep.rep_id,
      repName: rep.rep_name,
      belowBenchmarkSessions,
      scores: CATEGORY_META.reduce<Record<AnalyticsCategoryKey, number>>((accumulator, category) => {
        accumulator[category.key] = getHeatmapScore(progress, category.key);
        return accumulator;
      }, {} as Record<AnalyticsCategoryKey, number>),
    };
  });
}

export function TeamSkillHeatmap({
  managerId,
  reps,
  days,
  dateFrom,
  dateTo,
}: TeamSkillHeatmapProps) {
  const navigate = useNavigate();
  const [rows, setRows] = useState<HeatmapRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadRows() {
      if (!managerId || !reps.length) {
        if (active) {
          setRows([]);
          setLoading(false);
          setError(null);
        }
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const progressRows = await Promise.all(
          reps.map((rep) =>
            fetchRepProgress(managerId, rep.rep_id, {
              days,
              dateFrom,
              dateTo,
              limit: 60,
            })
          )
        );

        if (!active) {
          return;
        }

        setRows(buildHeatmapRows(reps, progressRows));
      } catch (loadError) {
        if (!active) {
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "Failed to load team skill heatmap.");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadRows();

    return () => {
      active = false;
    };
  }, [dateFrom, dateTo, days, managerId, reps]);

  const cells = useMemo<HeatmapCell[]>(
    () =>
      rows.flatMap((row, rowIndex) =>
        CATEGORY_META.map((category, columnIndex) => ({
          value: [columnIndex, rowIndex, row.scores[category.key]],
          repId: row.repId,
          repName: row.repName,
          category: category.key,
          belowBenchmarkSessions: row.belowBenchmarkSessions,
        }))
      ),
    [rows]
  );

  const option = useMemo<EChartsOption>(() => {
    return {
      backgroundColor: "transparent",
      animationDuration: 800,
      animationEasing: "cubicOut",
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(252,248,242,0.96)",
        borderColor: "rgba(45,90,61,0.12)",
        textStyle: { color: "#1d2a20" },
        formatter: (params: unknown) => {
          const cell = (params as { data?: HeatmapCell }).data;
          if (!cell) {
            return "";
          }
          const categoryLabel = CATEGORY_META[cell.value[0]]?.label ?? cell.category;
          return [
            `<strong>${cell.repName}</strong>`,
            `${categoryLabel}: ${cell.value[2].toFixed(1)}`,
            `${cell.belowBenchmarkSessions} sessions below benchmark`,
          ].join("<br/>");
        },
      },
      grid: { top: 20, right: 10, bottom: 12, left: 130 },
      xAxis: {
        type: "category",
        data: CATEGORY_META.map((category) => category.label),
        axisLabel: { color: "#5a6e5a", fontSize: 11, interval: 0 },
        axisLine: { lineStyle: { color: "rgba(45,90,61,0.12)" } },
        splitArea: { show: true, areaStyle: { color: ["rgba(255,255,255,0.14)", "rgba(255,255,255,0.06)"] } },
      },
      yAxis: {
        type: "category",
        data: rows.map((row) => row.repName),
        axisLabel: { color: "#1a2e1a", fontSize: 11, width: 120, overflow: "truncate" },
        axisLine: { lineStyle: { color: "rgba(45,90,61,0.12)" } },
        splitArea: { show: true, areaStyle: { color: ["transparent"] } },
      },
      series: [
        {
          type: "heatmap",
          data: cells.map((cell) => ({
            ...cell,
            itemStyle: {
              color: scoreColor(cell.value[2]),
              borderColor: "rgba(255,255,255,0.45)",
              borderWidth: 1,
              borderRadius: 14,
            },
          })),
          label: {
            show: true,
            formatter: (params: unknown) => {
              const cell = (params as { data?: HeatmapCell }).data;
              return cell ? cell.value[2].toFixed(1) : "";
            },
            color: "#fffdf8",
            fontWeight: 700,
            fontSize: 11,
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 18,
              shadowColor: "rgba(17,24,39,0.18)",
            },
          },
        },
      ],
    };
  }, [cells, rows]);

  if (loading) {
    return (
      <div className="space-y-2">
        {reps.map((rep) => (
          <div key={rep.rep_id} className="grid grid-cols-[96px_repeat(5,minmax(0,1fr))] gap-2">
            <ChartSkeleton heightClass="h-10" className="rounded-xl" />
            {CATEGORY_META.map((category) => (
              <ChartSkeleton key={`${rep.rep_id}-${category.key}`} heightClass="h-10" className="rounded-xl" />
            ))}
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return <EmptyState variant="error" message={error} />;
  }

  if (!rows.length) {
    return <EmptyState variant="empty" message="No rep category data in this window." />;
  }

  return (
    <EChartSurface
      option={option}
      height={Math.max(240, rows.length * 44 + 90)}
      onEvents={{
        click: (params) => {
          const cell = (params as { data?: HeatmapCell }).data;
          if (!cell) {
            return;
          }
          navigate(`/manager/reps/${cell.repId}/progress?category=${cell.category}`);
        },
      }}
    />
  );
}
