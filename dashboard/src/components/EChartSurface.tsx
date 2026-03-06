import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

type Props = {
  option: EChartsOption;
  height?: number;
  className?: string;
};

export function EChartSurface({ option, height = 320, className = "" }: Props) {
  return (
    <div className={className}>
      <ReactECharts
        option={option}
        notMerge
        lazyUpdate
        opts={{ renderer: "canvas" }}
        style={{ width: "100%", height }}
      />
    </div>
  );
}
