import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "./EChartSurface";
import { EmptyState } from "./shared/EmptyState";
import { PASSING_SCORE } from "../lib/analytics";
import type { CommandCenterResponse } from "../lib/types";

type RepRiskQuadrantProps = {
  reps: CommandCenterResponse["rep_risk_matrix"];
};

type QuadrantPoint = CommandCenterResponse["rep_risk_matrix"][number] & {
  value: [number, number, number];
};

function bubbleColor(level: CommandCenterResponse["rep_risk_matrix"][number]["risk_level"]): string {
  if (level === "high") {
    return "#dc2626";
  }
  if (level === "medium") {
    return "#f59e0b";
  }
  return "#2D5A3D";
}

export function RepRiskQuadrant({ reps }: RepRiskQuadrantProps) {
  const navigate = useNavigate();

  const option = useMemo<EChartsOption>(() => {
    if (!reps.length) {
      return {};
    }

    const deltas = reps.map((rep) => rep.score_delta);
    const minDelta = Math.min(...deltas, -1);
    const maxDelta = Math.max(...deltas, 1);
    const deltaPadding = Math.max(0.5, (maxDelta - minDelta) * 0.15);
    const points: QuadrantPoint[] = reps.map((rep) => ({
      ...rep,
      value: [rep.score_delta, rep.average_score, rep.volatility],
    }));

    return {
      backgroundColor: "transparent",
      animationDuration: 600,
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(252,248,242,0.96)",
        borderColor: "rgba(45,90,61,0.12)",
        textStyle: { color: "#1d2a20" },
        formatter: (params: unknown) => {
          const point = (params as { data?: QuadrantPoint }).data;
          if (!point) {
            return "";
          }
          return [
            `<strong>${point.rep_name}</strong>`,
            `Score: ${point.average_score.toFixed(1)}`,
            `Delta: ${point.score_delta >= 0 ? "+" : ""}${point.score_delta.toFixed(1)}`,
            `Risk: ${point.risk_level}`,
            "View Rep →",
          ].join("<br/>");
        },
      },
      grid: { top: 36, right: 20, bottom: 34, left: 40 },
      xAxis: {
        type: "value",
        min: minDelta - deltaPadding,
        max: maxDelta + deltaPadding,
        name: "Trend (score delta)",
        nameLocation: "middle",
        nameGap: 26,
        axisLabel: {
          color: "#5a6e5a",
          fontSize: 11,
          formatter: (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(1)}`,
        },
        splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 10,
        name: "Average score",
        nameLocation: "middle",
        nameGap: 38,
        axisLabel: { color: "#5a6e5a", fontSize: 11 },
        splitLine: { lineStyle: { color: "rgba(45,90,61,0.08)", type: "dashed" } },
      },
      graphic: [
        { type: "text", left: "9%", top: 8, style: { text: "At Risk", fill: "rgba(180,32,32,0.8)", font: '600 12px "Avenir Next"' } },
        { type: "text", right: "11%", top: 8, style: { text: "Rising Stars", fill: "rgba(45,90,61,0.8)", font: '600 12px "Avenir Next"' } },
        { type: "text", left: "9%", bottom: 10, style: { text: "Struggling", fill: "rgba(180,32,32,0.8)", font: '600 12px "Avenir Next"' } },
        { type: "text", right: "11%", bottom: 10, style: { text: "Plateaued", fill: "rgba(90,110,90,0.8)", font: '600 12px "Avenir Next"' } },
      ],
      series: [
        {
          type: "scatter",
          data: points,
          symbolSize: (_value: unknown, params: unknown) => {
            const point = (params as { data?: QuadrantPoint }).data;
            return 18 + Math.max(0, (point?.volatility ?? 0) * 10);
          },
          itemStyle: {
            color: (params: unknown) => {
              const point = (params as { data?: QuadrantPoint }).data;
              return bubbleColor(point?.risk_level ?? "low");
            },
            opacity: 0.88,
            shadowBlur: 16,
            shadowColor: "rgba(20,20,20,0.14)",
          },
          animationDelay: (index: number) => index * 70,
          markLine: {
            symbol: "none",
            lineStyle: { type: "dashed", color: "rgba(26,46,26,0.24)" },
            data: [{ xAxis: 0 }, { yAxis: PASSING_SCORE }],
          },
        },
      ],
    };
  }, [reps]);

  if (!reps.length) {
    return <EmptyState variant="empty" message="No rep risk signals yet." />;
  }

  return (
    <EChartSurface
      option={option}
      height={340}
      onEvents={{
        click: (params) => {
          const point = (params as { data?: QuadrantPoint }).data;
          if (!point) {
            return;
          }
          navigate(`/manager/reps/${point.rep_id}/progress`);
        },
      }}
    />
  );
}
