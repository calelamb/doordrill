import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import { EChartSurface } from "./EChartSurface";
import { EmptyState } from "./shared/EmptyState";
import type { ScenarioIntelligenceResponse } from "../lib/types";

type ObjectionTreemapProps = {
  items: ScenarioIntelligenceResponse["objection_failure_map"];
  scenarios: ScenarioIntelligenceResponse["items"];
  selectedTag: string | null;
  onSelectTag: (tag: string | null) => void;
};

type TreemapNode = {
  name: string;
  value: number;
  rawTag: string;
  appearanceRate: number;
  scenarioCount: number;
};

function prettifyTag(tag: string): string {
  return tag
    .split(/[_-]/g)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

function rateColor(rate: number): string {
  if (rate > 0.6) {
    return "#dc2626";
  }
  if (rate >= 0.4) {
    return "#f59e0b";
  }
  return "#2D5A3D";
}

export function ObjectionTreemap({
  items,
  scenarios,
  selectedTag,
  onSelectTag,
}: ObjectionTreemapProps) {
  const nodes = useMemo<TreemapNode[]>(() => {
    const scenarioSessions = new Map(scenarios.map((scenario) => [scenario.scenario_id, scenario.session_count]));
    const grouped = new Map<
      string,
      {
        count: number;
        scenarioIds: Set<string>;
        weightedSessions: number;
      }
    >();

    for (const item of items) {
      const existing = grouped.get(item.objection_tag) ?? {
        count: 0,
        scenarioIds: new Set<string>(),
        weightedSessions: 0,
      };

      existing.count += item.count;
      if (!existing.scenarioIds.has(item.scenario_id)) {
        existing.weightedSessions += scenarioSessions.get(item.scenario_id) ?? 0;
        existing.scenarioIds.add(item.scenario_id);
      }
      grouped.set(item.objection_tag, existing);
    }

    return Array.from(grouped.entries())
      .map(([tag, group]) => ({
        name: prettifyTag(tag),
        rawTag: tag,
        value: group.count,
        appearanceRate:
          group.weightedSessions > 0 ? Number((group.count / group.weightedSessions).toFixed(2)) : 0,
        scenarioCount: group.scenarioIds.size,
      }))
      .sort((left, right) => right.value - left.value);
  }, [items, scenarios]);

  const option = useMemo<EChartsOption>(() => {
    return {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (params: unknown) => {
          const node = (params as { data?: TreemapNode }).data;
          if (!node) {
            return "";
          }
          return [
            `<strong>${node.name}</strong>`,
            `${node.value} objection events`,
            `${Math.round(node.appearanceRate * 100)}% appearance rate`,
            `${node.scenarioCount} scenarios impacted`,
          ].join("<br/>");
        },
      },
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          label: {
            show: true,
            formatter: (params: unknown) => {
              const node = (params as { data?: TreemapNode }).data;
              return node ? `${node.name}\n${node.value}` : "";
            },
            color: "#fffdf8",
            fontWeight: 700,
          },
          upperLabel: { show: false },
          itemStyle: {
            borderColor: "rgba(255,255,255,0.4)",
            borderWidth: 2,
            gapWidth: 4,
          },
          animationDuration: 850,
          data: nodes.map((node) => ({
            ...node,
            itemStyle: {
              color: rateColor(node.appearanceRate),
              borderColor:
                selectedTag === node.rawTag ? "rgba(26,26,26,0.9)" : "rgba(255,255,255,0.4)",
              borderWidth: selectedTag === node.rawTag ? 3 : 2,
            },
          })),
        },
      ],
    };
  }, [nodes, selectedTag]);

  if (!nodes.length) {
    return <EmptyState variant="empty" message="No objection clusters available yet." />;
  }

  return (
    <EChartSurface
      option={option}
      height={320}
      onEvents={{
        click: (params) => {
          const node = (params as { data?: TreemapNode }).data;
          if (!node) {
            return;
          }
          onSelectTag(selectedTag === node.rawTag ? null : node.rawTag);
        },
      }}
    />
  );
}
