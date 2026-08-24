"use client";

import { HeatmapChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildTimelineAxisSpecs,
  formatAxisTick,
} from "../../lib/jjwxc/timeline-axis";
import type {
  JjwxcCorrelationCell,
  JjwxcMetricName,
  JjwxcMultivariateResponse,
  JjwxcNormalizedTrendPoint,
  JjwxcTimelineMetricName,
  JjwxcTrendPoint,
} from "../../types/api";

echarts.use([
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  HeatmapChart,
  LineChart,
  CanvasRenderer,
]);

const timelineMetrics: Array<{ key: JjwxcTimelineMetricName; label: string }> =
  [
    { key: "reviews", label: "书评" },
    { key: "favorites", label: "收藏" },
    { key: "points", label: "积分" },
    { key: "words", label: "字数" },
    { key: "clicks", label: "非 V 章均点击" },
  ];

const allMetrics: Array<{ key: JjwxcMetricName; label: string }> = [
  ...timelineMetrics,
  { key: "synopsis_chars", label: "文案字符数" },
];

const colors: Record<JjwxcTimelineMetricName, string> = {
  reviews: "#ffb5d2",
  favorites: "#8de2cb",
  points: "#f6c969",
  words: "#8cb8ff",
  clicks: "#c6a7ff",
};

function rawValue(
  point: JjwxcTrendPoint,
  metric: JjwxcTimelineMetricName,
): number | null {
  if (metric === "reviews") return point.total_review_count;
  if (metric === "favorites") return point.total_favorite_count;
  if (metric === "points") return point.total_points;
  if (metric === "words") return point.total_word_count;
  return point.mean_non_v_chapter_click_count;
}

function labelFor(metric: JjwxcMetricName) {
  return allMetrics.find((item) => item.key === metric)?.label ?? metric;
}

function TimelineChart({
  timeline,
  normalized,
  metrics,
  indexed,
  label,
}: {
  timeline: JjwxcTrendPoint[];
  normalized: JjwxcNormalizedTrendPoint[];
  metrics: JjwxcTimelineMetricName[];
  indexed: boolean;
  label: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const axisSpecs = useMemo(() => {
    const maxima: Partial<Record<JjwxcTimelineMetricName, number>> = {};
    for (const metric of metrics) {
      maxima[metric] = Math.max(
        0,
        ...timeline.map((point) => rawValue(point, metric) ?? 0),
      );
    }
    return buildTimelineAxisSpecs(metrics, maxima);
  }, [metrics, timeline]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || timeline.length === 0) return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    chart.setOption({
      animationDuration: 300,
      color: metrics.map((metric) => colors[metric]),
      grid: {
        left: indexed ? 72 : 92,
        right: indexed ? 28 : axisSpecs.length >= 3 ? 176 : 96,
        top: 72,
        bottom: 38,
      },
      legend: { textStyle: { color: "#b9adb6" } },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: timeline.map((item) => item.day.slice(5)),
        axisLabel: { color: "#b9adb6" },
        axisLine: { lineStyle: { color: "rgba(255,255,255,.15)" } },
      },
      yAxis: indexed
        ? [
            {
              type: "value",
              name: "相对变化（首值 = 100%）",
              nameTextStyle: { color: "#b9adb6" },
              axisLabel: {
                color: "#b9adb6",
                formatter: (value: number) => `${(value / 100).toFixed(0)}%`,
              },
              splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
            },
          ]
        : axisSpecs.map((axis, index) => ({
            type: "value",
            position: axis.position,
            offset: axis.offset,
            name: `${axis.label}（${axis.displayUnit}）`,
            nameLocation: "middle",
            nameGap: axis.position === "left" ? 62 : 66,
            nameTextStyle: { color: colors[axis.metric], fontSize: 11 },
            axisLine: { show: true, lineStyle: { color: colors[axis.metric] } },
            axisTick: { show: true, lineStyle: { color: colors[axis.metric] } },
            axisLabel: {
              color: colors[axis.metric],
              formatter: (value: number) => formatAxisTick(value, axis.divisor),
            },
            splitLine:
              index === 0
                ? { lineStyle: { color: "rgba(255,255,255,.08)" } }
                : { show: false },
          })),
      series: metrics.map((metric, index) => ({
        name: labelFor(metric),
        type: "line",
        yAxisIndex: indexed ? 0 : index,
        smooth: true,
        connectNulls: false,
        symbolSize: 7,
        data: indexed
          ? normalized.map((item) => item.values[metric])
          : timeline.map((item) => rawValue(item, metric)),
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [axisSpecs, indexed, metrics, normalized, timeline]);

  return (
    <div className="timeline-chart-block">
      <div className="axis-key" aria-label="纵轴与统计口径">
        {indexed ? (
          <span>
            <i style={{ background: "#b9adb6" }} />
            左轴 · 所有已选指标 · 基准指数
          </span>
        ) : (
          axisSpecs.map((axis) => (
            <span key={axis.metric}>
              <i style={{ background: colors[axis.metric] }} />
              {axis.position === "left"
                ? "左轴"
                : axis.offset
                  ? "右轴（外侧）"
                  : "右轴"}
              {` · ${axis.label} · ${axis.statistic} · ${axis.displayUnit}`}
            </span>
          ))
        )}
      </div>
      <div
        className="analysis-chart"
        ref={containerRef}
        role="img"
        aria-label={label}
      />
    </div>
  );
}

function CorrelationHeatmap({
  cells,
  metrics,
}: {
  cells: JjwxcCorrelationCell[];
  metrics: JjwxcMetricName[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || metrics.length < 2) return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    const labels = metrics.map(labelFor);
    const data = cells
      .filter(
        (cell) =>
          metrics.includes(cell.x_metric) && metrics.includes(cell.y_metric),
      )
      .map((cell) => [
        metrics.indexOf(cell.x_metric),
        metrics.indexOf(cell.y_metric),
        cell.coefficient === null ? "-" : Number(cell.coefficient.toFixed(3)),
        cell.paired_count,
      ]);
    chart.setOption({
      animationDuration: 250,
      grid: { left: 96, right: 34, top: 22, bottom: 86 },
      tooltip: { trigger: "item" },
      xAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#b9adb6", rotate: 32 },
        splitArea: { show: true },
      },
      yAxis: {
        type: "category",
        data: labels,
        axisLabel: { color: "#b9adb6" },
        splitArea: { show: true },
      },
      visualMap: {
        show: false,
        min: -1,
        max: 1,
        dimension: 2,
        calculable: false,
        inRange: {
          color: [
            "#294a8a",
            "#3a7bbf",
            "#66c2c9",
            "#e8ece9",
            "#f4d35e",
            "#f28e5b",
            "#b3263d",
          ],
        },
      },
      series: [
        {
          name: "Pearson 相关系数",
          type: "heatmap",
          data,
          label: {
            show: true,
            color: "#fffafc",
            textBorderColor: "rgba(19, 13, 18, 0.72)",
            textBorderWidth: 3,
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,.45)" },
          },
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [cells, metrics]);

  return (
    <div className="correlation-figure">
      <div
        className="analysis-chart correlation-chart"
        ref={containerRef}
        role="img"
        aria-label="作品指标 Pearson 相关矩阵热力图"
      />
      <div className="correlation-scale" aria-label="相关系数颜色图例：蓝色为负相关，浅灰为弱相关，黄色至红色为正相关">
        <span>强负相关</span>
        <i aria-hidden="true" />
        <span>强正相关</span>
      </div>
      <div className="correlation-scale-values">
        <span>−1.0</span>
        <span>弱相关 · 0</span>
        <span>+1.0</span>
      </div>
    </div>
  );
}

export function MultivariateExplorer({
  data,
}: {
  data: JjwxcMultivariateResponse;
}) {
  const [indexed, setIndexed] = useState(true);
  const [timelineSelection, setTimelineSelection] = useState<
    JjwxcTimelineMetricName[]
  >(["reviews", "favorites", "clicks"]);
  const [matrixSelection, setMatrixSelection] = useState<JjwxcMetricName[]>(
    allMetrics.map((item) => item.key),
  );

  function toggleTimeline(metric: JjwxcTimelineMetricName) {
    setTimelineSelection((current) => {
      if (current.includes(metric)) {
        return current.length === 1
          ? current
          : current.filter((item) => item !== metric);
      }
      return current.length >= 3 ? current : [...current, metric];
    });
  }

  function toggleMatrix(metric: JjwxcMetricName) {
    setMatrixSelection((current) => {
      if (current.includes(metric)) {
        return current.length <= 2
          ? current
          : current.filter((item) => item !== metric);
      }
      return [...current, metric];
    });
  }

  const clickSummary = data.summaries.find((item) => item.metric === "clicks");

  return (
    <div className="analysis-stack">
      <section className="chart-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">MULTI-METRIC · MAX 3</p>
            <h2>一条时间轴，多量对比</h2>
          </div>
          <button
            className="mode-toggle"
            type="button"
            onClick={() => setIndexed((value) => !value)}
          >
            {indexed ? "切换为原值" : "切换为基准指数"}
          </button>
        </div>
        <div className="metric-picker" aria-label="时间轴指标，最多选择三个">
          {timelineMetrics.map((metric) => {
            const selected = timelineSelection.includes(metric.key);
            const disabled = !selected && timelineSelection.length >= 3;
            return (
              <button
                key={metric.key}
                type="button"
                aria-pressed={selected}
                disabled={disabled}
                onClick={() => toggleTimeline(metric.key)}
              >
                {metric.label}
              </button>
            );
          })}
        </div>
        <TimelineChart
          timeline={data.timeline}
          normalized={data.normalized_timeline}
          metrics={timelineSelection}
          indexed={indexed}
          label="JJWXC 多指标时间轴图"
        />
        <p className="analysis-note">
          基准指数把各序列首个有效值设为
          100%，只比较变化速度；原值模式会为每个变量分配独立纵轴，并按数值量级自动选用千、万或亿。
        </p>
      </section>

      <section className="chart-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">PAIRWISE COMPLETE · 2D + COLOR</p>
            <h2>可调变量相关矩阵</h2>
          </div>
          <span>仅描述关联，不推断因果</span>
        </div>
        <div className="metric-picker" aria-label="矩阵指标，至少选择两个">
          {allMetrics.map((metric) => (
            <button
              key={metric.key}
              type="button"
              aria-pressed={matrixSelection.includes(metric.key)}
              onClick={() => toggleMatrix(metric.key)}
            >
              {metric.label}
            </button>
          ))}
        </div>
        <CorrelationHeatmap
          cells={data.correlation_matrix}
          metrics={matrixSelection}
        />
        <p className="analysis-note">
          横轴、纵轴和颜色共三维；蓝色表示负相关，浅灰表示弱相关，黄色至红色表示正相关。
          缺失点击量时按每对变量的共同有效样本计算，悬停可查看样本数。
        </p>
      </section>

      <section className="summary-panel" aria-labelledby="summary-title">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">HIGH-DIMENSIONAL SUMMARY</p>
            <h2 id="summary-title">高维统计特性</h2>
          </div>
          <span>中位数 · 四分位距 · 变异系数 · 覆盖率</span>
        </div>
        <div className="summary-grid">
          {data.summaries.map((summary) => (
            <article key={summary.metric} className="summary-card">
              <h3>{summary.label}</h3>
              <strong>
                {summary.median === null
                  ? "缺失"
                  : formatMetric(summary.median)}
              </strong>
              <dl>
                <div>
                  <dt>覆盖率</dt>
                  <dd>{(summary.coverage_basis_points / 100).toFixed(0)}%</dd>
                </div>
                <div>
                  <dt>四分位距</dt>
                  <dd>
                    {summary.p25 === null || summary.p75 === null
                      ? "—"
                      : formatMetric(summary.p75 - summary.p25)}
                  </dd>
                </div>
                <div>
                  <dt>变异系数</dt>
                  <dd>
                    {summary.coefficient_of_variation === null
                      ? "—"
                      : summary.coefficient_of_variation.toFixed(2)}
                  </dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
        <p className="analysis-note">
          点击量口径为“非 V 章节章均点击数”，
          {data.data_mode === "database_snapshot" ? "当前数据库快照" : "当前演示"}
          覆盖{" "}
          {clickSummary?.observed_count ?? 0} /{" "}
          {data.timeline.at(-1)?.observed_novel_count ?? 0}
          ；未公开的值保持为空。
          文案仅保存字符数、句数和固定主题词，不保存原文。
        </p>
      </section>
    </div>
  );
}

function formatMetric(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 1,
    notation: "compact",
  }).format(value);
}
