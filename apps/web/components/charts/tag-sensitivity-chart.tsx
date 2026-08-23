"use client";

import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import type { TagSensitivityPoint } from "../../types/api";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

export function TagSensitivityChart({ points }: { points: TagSensitivityPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || points.length === 0) return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    chart.setOption({
      animation: false,
      grid: { left: 52, right: 28, top: 28, bottom: 48 },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        name: "最小共现",
        data: points.map((point) => String(point.minimum_cooccurrence)),
        axisLabel: { color: "#c9bec7" },
        nameTextStyle: { color: "#c9bec7" },
      },
      yAxis: {
        type: "value",
        name: "合格关系",
        minInterval: 1,
        axisLabel: { color: "#c9bec7" },
        nameTextStyle: { color: "#c9bec7" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,0.09)" } },
      },
      series: [{
        type: "line",
        smooth: false,
        symbolSize: 9,
        data: points.map((point) => point.eligible_edge_count),
        lineStyle: { color: "#8de2cb", width: 3 },
        itemStyle: { color: "#ffb5d2", borderColor: "#100d12", borderWidth: 2 },
        areaStyle: { color: "rgba(141, 226, 203, 0.08)" },
      }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [points]);

  return (
    <div
      className="tag-sensitivity-chart"
      ref={containerRef}
      role="img"
      aria-label={`标签关系阈值曲线，共 ${points.length} 个固定阈值`}
    />
  );
}
