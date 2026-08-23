"use client";

import { LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { compactAxisUnit, formatAxisTick } from "../../lib/jjwxc/timeline-axis";
import type { JjwxcTrendPoint } from "../../types/api";

echarts.use([
  GridComponent,
  LegendComponent,
  TooltipComponent,
  LineChart,
  CanvasRenderer,
]);

export function JjwxcTrendChart({ items }: { items: JjwxcTrendPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || items.length === 0) return;
    const reviewUnit = compactAxisUnit(
      Math.max(...items.map((item) => item.total_review_count)),
    );
    const favoriteUnit = compactAxisUnit(
      Math.max(...items.map((item) => item.total_favorite_count)),
    );
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    chart.setOption({
      animationDuration: 350,
      color: ["#ffb5d2", "#8de2cb"],
      grid: { left: 92, right: 92, top: 72, bottom: 34 },
      legend: { textStyle: { color: "#b9adb6" } },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: items.map((item) => item.day.slice(5)),
        axisLabel: { color: "#b9adb6" },
        axisLine: { lineStyle: { color: "rgba(255,255,255,.15)" } },
      },
      yAxis: [
        {
          type: "value",
          name: `总书评（${reviewUnit.prefix}条）`,
          nameLocation: "middle",
          nameGap: 62,
          nameTextStyle: { color: "#ffb5d2" },
          axisLine: { show: true, lineStyle: { color: "#ffb5d2" } },
          axisLabel: {
            color: "#ffb5d2",
            formatter: (value: number) =>
              formatAxisTick(value, reviewUnit.divisor),
          },
          splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
        },
        {
          type: "value",
          name: `总收藏（${favoriteUnit.prefix}次）`,
          nameLocation: "middle",
          nameGap: 62,
          nameTextStyle: { color: "#8de2cb" },
          axisLine: { show: true, lineStyle: { color: "#8de2cb" } },
          axisLabel: {
            color: "#8de2cb",
            formatter: (value: number) =>
              formatAxisTick(value, favoriteUnit.divisor),
          },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "总书评",
          type: "line",
          smooth: true,
          data: items.map((item) => item.total_review_count),
        },
        {
          name: "总收藏",
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          data: items.map((item) => item.total_favorite_count),
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [items]);

  if (items.length === 0) return <p className="chart-empty">暂无趋势快照。</p>;
  return (
    <div className="timeline-chart-block">
      <div className="axis-key" aria-label="首页趋势图纵轴与统计口径">
        <span>
          <i style={{ background: "#ffb5d2" }} />
          左轴 · 总书评 · 求和统计
        </span>
        <span>
          <i style={{ background: "#8de2cb" }} />
          右轴 · 总收藏 · 求和统计
        </span>
      </div>
      <div
        className="trend-chart"
        ref={containerRef}
        role="img"
        aria-label="JJWXC 百合小说书评与收藏趋势图"
      />
    </div>
  );
}
