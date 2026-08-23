"use client";

import * as echarts from "echarts/core";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { LineChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { trendSeries, type MetricTrendPoint } from "../../lib/chart/trend";

echarts.use([GridComponent, LegendComponent, TooltipComponent, LineChart, CanvasRenderer]);

export function MetricTrendChart({ items }: { items: MetricTrendPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || items.length === 0) {
      return;
    }
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    const series = trendSeries(items);
    chart.setOption({
      animation: false,
      color: ["#ffb5d2", "#8de2cb"],
      grid: { left: 42, right: 18, top: 42, bottom: 30 },
      legend: { textStyle: { color: "#b9adb6" } },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: series.days,
        axisLabel: { color: "#b9adb6" },
        axisLine: { lineStyle: { color: "rgba(255,255,255,.15)" } },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#b9adb6" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
      },
      series: [
        { name: "点赞", type: "line", smooth: true, data: series.likes },
        { name: "收藏", type: "line", smooth: true, data: series.bookmarks },
      ],
    });
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(container);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [items]);

  if (items.length === 0) {
    return <p className="chart-empty">所选时间段暂无指标快照。</p>;
  }
  return <div className="trend-chart" ref={containerRef} role="img" aria-label="点赞与收藏趋势图" />;
}
