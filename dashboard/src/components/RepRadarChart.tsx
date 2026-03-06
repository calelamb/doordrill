import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "./EChartSurface";
import { CATEGORY_META, getCategoryLabel, type AnalyticsCategoryKey } from "../lib/analytics";

type RepRadarChartProps = {
  current: Record<string, number>;
  previous: Record<string, number>;
  benchmarks: Record<string, number>;
  height?: number;
};

function getValue(record: Record<string, number>, key: AnalyticsCategoryKey): number {
  return Number((record[key] ?? 0).toFixed(2));
}

export function RepRadarChart({
  current,
  previous,
  benchmarks,
  height = 320,
}: RepRadarChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const currentValues = CATEGORY_META.map((category) => getValue(current, category.key));
    const previousValues = CATEGORY_META.map((category) => getValue(previous, category.key));

    return {
      backgroundColor: "transparent",
      animationDuration: 1000,
      animationEasing: "elasticOut",
      tooltip: {
        trigger: "item",
        backgroundColor: "rgba(252,248,242,0.96)",
        borderColor: "rgba(45,90,61,0.12)",
        textStyle: { color: "#1d2a20" },
      },
      legend: {
        bottom: 0,
        itemWidth: 14,
        itemHeight: 14,
        textStyle: { color: "#5a6e5a", fontSize: 11 },
      },
      radar: {
        radius: "62%",
        center: ["50%", "46%"],
        splitNumber: 5,
        indicator: CATEGORY_META.map((category) => ({
          name: `${getCategoryLabel(category.key)} (avg: ${(benchmarks[category.key] ?? 0).toFixed(1)})`,
          max: 10,
        })),
        axisName: {
          color: "#5a6e5a",
          fontSize: 11,
          lineHeight: 16,
        },
        splitArea: {
          areaStyle: {
            color: [
              "rgba(255,255,255,0.20)",
              "rgba(255,255,255,0.12)",
              "rgba(255,255,255,0.08)",
              "rgba(255,255,255,0.05)",
              "rgba(255,255,255,0.03)",
            ],
          },
        },
        splitLine: { lineStyle: { color: "rgba(45,90,61,0.12)" } },
        axisLine: { lineStyle: { color: "rgba(45,90,61,0.14)" } },
      },
      series: [
        {
          type: "radar",
          symbolSize: 6,
          data: [
            {
              value: currentValues,
              name: "Current period",
              lineStyle: { color: "#2D5A3D", width: 3 },
              itemStyle: { color: "#2D5A3D" },
              areaStyle: { color: "rgba(45,90,61,0.26)" },
            },
            {
              value: previousValues,
              name: "Previous period",
              lineStyle: { color: "#f59e0b", width: 2, type: "dashed" },
              itemStyle: { color: "#f59e0b" },
              areaStyle: { color: "rgba(245,158,11,0)" },
            },
          ],
        },
      ],
    };
  }, [benchmarks, current, previous]);

  return <EChartSurface option={option} height={height} notMerge={false} />;
}
