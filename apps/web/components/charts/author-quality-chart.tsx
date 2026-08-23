"use client";

import { ScatterChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import type {
  AuthorQualityMapItem,
  AuthorQualityQuadrant,
} from "../../types/api";

echarts.use([
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  ScatterChart,
  CanvasRenderer,
]);

const quadrants: Array<{
  key: AuthorQualityQuadrant;
  label: string;
  color: string;
}> = [
  { key: "core", label: "核心作者", color: "#8de2cb" },
  { key: "boutique", label: "精品作者", color: "#ffb5d2" },
  { key: "volume", label: "数量型作者", color: "#b9a7ff" },
  { key: "ordinary", label: "普通作者", color: "#8d8790" },
];

export function AuthorQualityChart({
  items,
  workThresholdX100,
  bookmarkThresholdX100,
}: {
  items: AuthorQualityMapItem[];
  workThresholdX100: number;
  bookmarkThresholdX100: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const counts = useMemo(
    () => new Map(
      quadrants.map(({ key }) => [key, items.filter((item) => item.quadrant === key).length]),
    ),
    [items],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || items.length === 0) {
      return;
    }
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    chart.setOption({
      animation: false,
      grid: { left: 58, right: 24, top: 54, bottom: 48 },
      legend: { textStyle: { color: "#b9adb6" } },
      tooltip: { trigger: "item" },
      xAxis: {
        type: "value",
        name: "作品数",
        nameTextStyle: { color: "#b9adb6" },
        axisLabel: { color: "#b9adb6" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
      },
      yAxis: {
        type: "value",
        name: "平均收藏",
        nameTextStyle: { color: "#b9adb6" },
        axisLabel: { color: "#b9adb6" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
      },
      series: quadrants.map(({ key, label, color }, index) => ({
        name: label,
        type: "scatter",
        itemStyle: { color },
        symbolSize: (value: number[]) => Math.max(10, Math.min(36, Math.sqrt(value[2] ?? 0) * 1.5)),
        data: items
          .filter((item) => item.quadrant === key)
          .map((item) => ({
            name: item.author_display_name,
            value: [
              item.work_count,
              item.average_public_bookmark_count_x100 / 100,
              item.total_public_like_count ?? 0,
            ],
          })),
        markLine: index === 0 ? {
          animation: false,
          label: { color: "#b9adb6" },
          lineStyle: { color: "rgba(255,255,255,.3)", type: "dashed" },
          symbol: "none",
          data: [
            { xAxis: workThresholdX100 / 100, name: "样本作品中位数" },
            { yAxis: bookmarkThresholdX100 / 100, name: "样本收藏中位数" },
          ],
        } : undefined,
      })),
    });
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(container);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [bookmarkThresholdX100, items, workThresholdX100]);

  if (items.length === 0) {
    return <p className="chart-empty">暂无具备收藏覆盖的作者样本。</p>;
  }
  return (
    <>
      <div
        className="quality-chart"
        ref={containerRef}
        role="img"
        aria-label="作者作品数、平均收藏与总点赞质量四象限图"
      />
      <p className="quality-legend" aria-label="作者质量象限样本数">
        {quadrants.map(({ key, label }) => (
          <span key={key}>{label} {counts.get(key) ?? 0}</span>
        ))}
      </p>
    </>
  );
}
