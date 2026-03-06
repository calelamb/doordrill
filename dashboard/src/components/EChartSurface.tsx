import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

type Props = {
  option: EChartsOption;
  height?: number;
  className?: string;
  notMerge?: boolean;
  onEvents?: Record<string, (params: unknown) => void>;
};

export function EChartSurface({
  option,
  height = 320,
  className = "",
  notMerge = true,
  onEvents,
}: Props) {
  return (
    <div className={className}>
      <ReactECharts
        option={option}
        notMerge={notMerge}
        lazyUpdate
        onEvents={onEvents}
        opts={{ renderer: "canvas" }}
        style={{ width: "100%", height }}
      />
    </div>
  );
}
