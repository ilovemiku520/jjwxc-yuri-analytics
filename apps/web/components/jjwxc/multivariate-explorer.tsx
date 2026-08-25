"use client";

import {
  BarChart,
  BoxplotChart,
  HeatmapChart,
  LineChart,
} from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildTimelineAxisSpecs,
  compactAxisUnit,
  formatAxisTick,
} from "../../lib/jjwxc/timeline-axis";
import {
  analyzeLogMomentCorrelation,
  type LogMomentCorrelationStats,
} from "../../lib/jjwxc/statistics";
import {
  MAX_IMPORTED_NOVEL_IDS,
  MIN_CORRELATION_SAMPLE_SIZE,
} from "../../lib/jjwxc/cohort-file";
import type {
  JjwxcCorrelationCell,
  JjwxcMetricName,
  JjwxcMultivariateResponse,
  JjwxcNovel,
  JjwxcNormalizedTrendPoint,
  JjwxcTimelineMetricName,
  JjwxcTrendPoint,
} from "../../types/api";

echarts.use([
  GridComponent,
  LegendComponent,
  DataZoomComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
  HeatmapChart,
  BarChart,
  BoxplotChart,
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
    { key: "v_clicks", label: "V 章均点击" },
  ];

const allMetrics: Array<{ key: JjwxcMetricName; label: string }> = [
  ...timelineMetrics,
  { key: "nutrition", label: "营养液" },
  { key: "first_clicks", label: "首章点击" },
  { key: "loyalty", label: "营养液/收藏投入比" },
  { key: "click_favorite", label: "首章点击/收藏转化比" },
  { key: "v_retention", label: "V/非 V 点击留存比（代理）" },
  { key: "synopsis_chars", label: "文案字符数" },
];

const matrixMetrics = allMetrics.filter((metric) => metric.key !== "v_clicks");

const colors: Record<JjwxcTimelineMetricName, string> = {
  reviews: "#ffb5d2",
  favorites: "#8de2cb",
  points: "#f6c969",
  words: "#8cb8ff",
  clicks: "#c6a7ff",
  v_clicks: "#ff9f7d",
};

function rawValue(
  point: JjwxcTrendPoint,
  metric: JjwxcTimelineMetricName,
): number | null {
  const divisor = Math.max(1, point.observed_novel_count);
  if (metric === "reviews") return point.total_review_count / divisor;
  if (metric === "favorites") return point.total_favorite_count / divisor;
  if (metric === "points") return point.total_points / divisor;
  if (metric === "words") return point.total_word_count / divisor;
  if (metric === "clicks") return point.mean_non_v_chapter_click_count;
  return point.mean_v_chapter_click_count;
}

function normalizeTimelineForRange(
  timeline: JjwxcTrendPoint[],
): JjwxcNormalizedTrendPoint[] {
  const baselines = Object.fromEntries(
    timelineMetrics.map(({ key }) => [
      key,
      timeline
        .map((point) => rawValue(point, key))
        .find((value) => value !== null && value !== 0) ?? null,
    ]),
  ) as Record<JjwxcTimelineMetricName, number | null>;
  return timeline.map((point) => ({
    day: point.day,
    values: Object.fromEntries(
      timelineMetrics.map(({ key }) => {
        const value = rawValue(point, key);
        const baseline = baselines[key];
        return [
          key,
          value !== null && baseline !== null
            ? Math.round((value * 10000) / baseline)
            : null,
        ];
      }),
    ) as Record<JjwxcTimelineMetricName, number | null>,
  }));
}

function labelFor(metric: JjwxcMetricName) {
  return allMetrics.find((item) => item.key === metric)?.label ?? metric;
}

function novelMetricValue(
  novel: JjwxcNovel,
  metric: JjwxcMetricName,
): number | null {
  if (metric === "reviews") return novel.review_count;
  if (metric === "favorites") return novel.favorite_count;
  if (metric === "nutrition") return novel.nutrition_count;
  if (metric === "first_clicks") return novel.first_chapter_click_count;
  if (metric === "loyalty") {
    return novel.nutrition_to_favorite_basis_points === null
      ? null
      : novel.nutrition_to_favorite_basis_points / 10_000;
  }
  if (metric === "click_favorite") {
    return novel.first_click_to_favorite_basis_points === null
      ? null
      : novel.first_click_to_favorite_basis_points / 10_000;
  }
  if (metric === "points") return novel.points;
  if (metric === "words") return novel.word_count;
  if (metric === "clicks") return novel.average_non_v_chapter_click_count;
  if (metric === "v_clicks") return novel.average_v_chapter_click_count;
  if (metric === "v_retention") {
    return novel.v_to_non_v_click_retention_basis_points === null
      ? null
      : novel.v_to_non_v_click_retention_basis_points / 10_000;
  }
  return novel.synopsis_char_count;
}

function DistributionTrendChart({
  timeline,
  metric,
}: {
  timeline: JjwxcTrendPoint[];
  metric: JjwxcTimelineMetricName;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const summaries = useMemo(
    () => timeline.map((point) => point.metric_distributions?.[metric] ?? null),
    [metric, timeline],
  );
  const latestIndex = summaries.findLastIndex(
    (summary) => (summary?.observed_count ?? 0) > 0,
  );
  const latest =
    latestIndex >= 0
      ? {
          day: timeline[latestIndex]?.day ?? "",
          summary: summaries[latestIndex] ?? null,
        }
      : null;

  useEffect(() => {
    const container = containerRef.current;
    if (
      !container ||
      !summaries.some((item) => (item?.observed_count ?? 0) > 0)
    )
      return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    const distributionMaximum = Math.max(
      0,
      ...summaries.flatMap((summary) =>
        summary ? [summary.upper_whisker ?? 0] : [],
      ),
    );
    const topMeanMaximum = Math.max(
      0,
      ...summaries.map((summary) => summary?.top_mean ?? 0),
    );
    const distributionUnit = compactAxisUnit(distributionMaximum);
    const topMeanUnit = compactAxisUnit(topMeanMaximum);
    const boxData = summaries.map((summary) =>
      summary &&
      summary.lower_whisker !== null &&
      summary.p25 !== null &&
      summary.median !== null &&
      summary.p75 !== null &&
      summary.upper_whisker !== null
        ? [
            summary.lower_whisker,
            summary.p25,
            summary.median,
            summary.p75,
            summary.upper_whisker,
          ]
        : null,
    );
    chart.setOption({
      animationDuration: 320,
      color: ["#8de2cb", "#f6c969"],
      grid: {
        left: 88,
        right: 92,
        top: 92,
        bottom: timeline.length > 14 ? 76 : 42,
      },
      legend: { textStyle: { color: "#b9adb6" } },
      tooltip: { trigger: "axis" },
      toolbox: {
        right: 8,
        feature: {
          dataZoom: { yAxisIndex: "none" },
          restore: {},
          saveAsImage: { name: `JJWXC-${labelFor(metric)}-时序分布` },
        },
        iconStyle: { borderColor: "#b9adb6" },
      },
      dataZoom:
        timeline.length > 14
          ? [
              { type: "inside", xAxisIndex: 0 },
              {
                type: "slider",
                xAxisIndex: 0,
                height: 18,
                bottom: 16,
                borderColor: "rgba(255,255,255,.12)",
                textStyle: { color: "#b9adb6" },
              },
            ]
          : [],
      xAxis: {
        type: "category",
        data: timeline.map((item) => item.day.slice(5)),
        axisLabel: { color: "#b9adb6" },
        axisLine: { lineStyle: { color: "rgba(255,255,255,.15)" } },
      },
      yAxis: [
        {
          type: "value",
          min: 0,
          name: `箱型分布（${distributionUnit.prefix || "原值"}）`,
          nameTextStyle: { color: "#8de2cb" },
          axisLabel: {
            color: "#b9adb6",
            formatter: (value: number) =>
              formatAxisTick(value, distributionUnit.divisor),
          },
          axisLine: { show: true, lineStyle: { color: "#8de2cb" } },
          splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
        },
        {
          type: "value",
          min: 0,
          name: `Top 10 均值（${topMeanUnit.prefix || "原值"}）`,
          nameTextStyle: { color: "#f6c969" },
          axisLabel: {
            color: "#b9adb6",
            formatter: (value: number) =>
              formatAxisTick(value, topMeanUnit.divisor),
          },
          axisLine: { show: true, lineStyle: { color: "#f6c969" } },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "箱型分布（Tukey）",
          type: "boxplot",
          yAxisIndex: 0,
          data: boxData,
          itemStyle: {
            color: "rgba(141,226,203,.24)",
            borderColor: "#8de2cb",
          },
        },
        {
          name: "Top 10 均值",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          symbolSize: 7,
          data: summaries.map((summary) => summary?.top_mean ?? null),
          itemStyle: { color: "#f6c969" },
          lineStyle: { color: "#f6c969", width: 2.5 },
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [metric, summaries, timeline]);

  const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
  return (
    <div className="distribution-timeline">
      {latest?.summary ? (
        <div className="distribution-summary-grid" aria-label="最新分布统计">
          <article>
            <span>最新统计日</span>
            <strong>{latest.day}</strong>
            <small>有效样本 n={latest.summary.observed_count}</small>
          </article>
          <article>
            <span>Top {latest.summary.top_group_count} 均值</span>
            <strong>{number.format(latest.summary.top_mean ?? 0)}</strong>
            <small>当日高位组</small>
          </article>
          <article>
            <span>中位数</span>
            <strong>{number.format(latest.summary.median ?? 0)}</strong>
            <small>对极端值更稳健</small>
          </article>
          <article>
            <span>Bottom {latest.summary.bottom_group_count} 均值</span>
            <strong>{number.format(latest.summary.bottom_mean ?? 0)}</strong>
            <small>当日低位组</small>
          </article>
        </div>
      ) : (
        <p className="analysis-note">当前数据源尚未保存逐日分布统计。</p>
      )}
      {latest?.summary ? (
        <div
          className="analysis-chart distribution-chart"
          ref={containerRef}
          role="img"
          aria-label={`${labelFor(metric)} Top 10 均值双轴与 Tukey 时序箱型图`}
        />
      ) : null}
    </div>
  );
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
      <div
        className="correlation-scale"
        aria-label="相关系数颜色图例：蓝色为负相关，浅灰为弱相关，黄色至红色为正相关"
      >
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

type CorrelationDisplayMode = "both" | "pearson" | "spearman";

type MetricComparison = {
  metric: JjwxcMetricName;
  label: string;
  stats: LogMomentCorrelationStats;
};

function formatStatistic(value: number | null, digits = 3): string {
  return value === null
    ? "—"
    : new Intl.NumberFormat("zh-CN", {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      }).format(value);
}

function CorrelationSampleComparison({ novels }: { novels: JjwxcNovel[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [rankingMetric, setRankingMetric] =
    useState<JjwxcMetricName>("favorites");
  const [displayMode, setDisplayMode] =
    useState<CorrelationDisplayMode>("both");
  const maximumSampleSize = Math.min(MAX_IMPORTED_NOVEL_IDS, novels.length);
  const [sampleSize, setSampleSize] = useState(
    Math.min(
      Math.max(MIN_CORRELATION_SAMPLE_SIZE, 1),
      Math.max(maximumSampleSize, 1),
    ),
  );
  const rankedNovels = useMemo(
    () =>
      [...novels]
        .filter((novel) => novelMetricValue(novel, rankingMetric) !== null)
        .sort(
          (left, right) =>
            (novelMetricValue(right, rankingMetric) ?? 0) -
              (novelMetricValue(left, rankingMetric) ?? 0) ||
            left.novel_id.localeCompare(right.novel_id),
        )
        .slice(0, sampleSize),
    [novels, rankingMetric, sampleSize],
  );
  const comparisons = useMemo<MetricComparison[]>(
    () =>
      allMetrics
        .filter((metric) => metric.key !== rankingMetric)
        .map((metric) => {
          const pairs = rankedNovels.flatMap((novel) => {
            const x = novelMetricValue(novel, rankingMetric);
            const y = novelMetricValue(novel, metric.key);
            return x === null || y === null
              ? []
              : ([[x, y]] as Array<[number, number]>);
          });
          return {
            metric: metric.key,
            label: metric.label,
            stats: analyzeLogMomentCorrelation(pairs),
          };
        })
        .filter(
          (item) => item.stats.pearson !== null || item.stats.spearman !== null,
        ),
    [rankedNovels, rankingMetric],
  );
  const eligibleComparisons = useMemo(
    () =>
      comparisons.filter(
        (item) => item.stats.pairedCount >= MIN_CORRELATION_SAMPLE_SIZE,
      ),
    [comparisons],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    const methods = (
      displayMode === "both" ? ["pearson", "spearman"] : [displayMode]
    ) as Array<"pearson" | "spearman">;
    chart.setOption({
      animationDuration: 250,
      color: ["#f28e5b", "#8cb8ff"],
      grid: { left: 155, right: 58, top: 48, bottom: 38 },
      legend: {
        data: methods.map((method) =>
          method === "pearson" ? "Pearson r" : "Spearman ρ",
        ),
        textStyle: { color: "#b9adb6" },
      },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "value",
        min: -1,
        max: 1,
        name: `与${labelFor(rankingMetric)}的相关效应量`,
        nameTextStyle: { color: "#b9adb6" },
        axisLabel: { color: "#b9adb6" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
      },
      yAxis: {
        type: "category",
        data: eligibleComparisons.map(
          (item) => `${item.label} · n=${item.stats.pairedCount}`,
        ),
        axisLabel: { color: "#b9adb6" },
      },
      series: methods.map((method) => ({
        name: method === "pearson" ? "Pearson r" : "Spearman ρ",
        type: "bar",
        barMaxWidth: 22,
        itemStyle: { color: method === "pearson" ? "#f28e5b" : "#8cb8ff" },
        data: eligibleComparisons.map((item) => {
          const value = item.stats[method];
          return value === null ? null : Number(value.toFixed(3));
        }),
        label: {
          show: displayMode !== "both",
          position: "right",
          color: "#f7f3f6",
        },
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [displayMode, eligibleComparisons, rankingMetric]);

  return (
    <section className="chart-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">N ≥ 30 · MOMENTS + ROBUST CORRELATION</p>
          <h2>可调样本作品相关系数比较</h2>
        </div>
        <span>效应量 · 稳健性 · 估计不确定性</span>
      </div>
      <div className="correlation-sample-control">
        <label htmlFor="correlation-sample-size">
          分析样本量
          <strong>{rankedNovels.length}</strong>
        </label>
        <input
          disabled={maximumSampleSize < MIN_CORRELATION_SAMPLE_SIZE}
          id="correlation-sample-size"
          max={Math.max(maximumSampleSize, MIN_CORRELATION_SAMPLE_SIZE)}
          min={MIN_CORRELATION_SAMPLE_SIZE}
          onChange={(event) => setSampleSize(Number(event.target.value))}
          step="1"
          type="range"
          value={Math.max(sampleSize, MIN_CORRELATION_SAMPLE_SIZE)}
        />
        <input
          aria-label="样本量精确值"
          disabled={maximumSampleSize < MIN_CORRELATION_SAMPLE_SIZE}
          max={Math.max(maximumSampleSize, MIN_CORRELATION_SAMPLE_SIZE)}
          min={MIN_CORRELATION_SAMPLE_SIZE}
          onChange={(event) => {
            const value = Number(event.target.value);
            setSampleSize(
              Math.min(
                Math.max(value, MIN_CORRELATION_SAMPLE_SIZE),
                maximumSampleSize,
              ),
            );
          }}
          type="number"
          value={Math.max(sampleSize, MIN_CORRELATION_SAMPLE_SIZE)}
        />
        <span>
          可用 {maximumSampleSize} 部 · 系数按每对变量的共同有效样本重新计算
        </span>
      </div>
      <div className="metric-picker" aria-label="前十榜单排序变量">
        {allMetrics.map((metric) => (
          <button
            aria-pressed={rankingMetric === metric.key}
            key={metric.key}
            onClick={() => setRankingMetric(metric.key)}
            type="button"
          >
            {metric.label}
          </button>
        ))}
      </div>
      <div
        className="metric-picker correlation-method-picker"
        aria-label="相关算法显示方式"
      >
        {(
          [
            ["both", "双方法校验"],
            ["pearson", "Pearson 线性"],
            ["spearman", "Spearman 秩相关"],
          ] as Array<[CorrelationDisplayMode, string]>
        ).map(([mode, label]) => (
          <button
            aria-pressed={displayMode === mode}
            key={mode}
            onClick={() => setDisplayMode(mode)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      <div
        aria-label={`按${labelFor(rankingMetric)}选出的可调样本作品相关系数比较图`}
        className="analysis-chart top-ten-correlation-chart"
        ref={containerRef}
        role="img"
      />
      <p className="top-ten-cohort-names" role="status">
        当前纳入 {rankedNovels.length} 部；{eligibleComparisons.length}{" "}
        个变量达到 n≥{MIN_CORRELATION_SAMPLE_SIZE} 的展示门槛。
      </p>
      {eligibleComparisons.length === 0 ? (
        <p className="cohort-sample-warning">
          当前没有变量对达到 30
          个共同有效样本，图表暂停展示，避免把小样本波动误作稳定关系。
        </p>
      ) : null}
      <details className="statistics-details">
        <summary>查看一阶矩、二阶矩与估计区间</summary>
        <div className="statistics-table-wrap">
          <table>
            <thead>
              <tr>
                <th>比较变量</th>
                <th>n</th>
                <th>一阶矩 μx / μy</th>
                <th>二阶中心矩 σ²x / σ²y</th>
                <th>协方差</th>
                <th>Pearson r（95% CI）</th>
                <th>Spearman ρ</th>
                <th>门槛</th>
              </tr>
            </thead>
            <tbody>
              {comparisons.map((item) => (
                <tr key={item.metric}>
                  <th scope="row">{item.label}</th>
                  <td>{item.stats.pairedCount}</td>
                  <td>
                    {formatStatistic(item.stats.xMean)} /{" "}
                    {formatStatistic(item.stats.yMean)}
                  </td>
                  <td>
                    {formatStatistic(item.stats.xSecondCentralMoment)} /{" "}
                    {formatStatistic(item.stats.ySecondCentralMoment)}
                  </td>
                  <td>{formatStatistic(item.stats.covariance)}</td>
                  <td>
                    {formatStatistic(item.stats.pearson)}（
                    {formatStatistic(item.stats.pearsonConfidenceLow)}，
                    {formatStatistic(item.stats.pearsonConfidenceHigh)}）
                  </td>
                  <td>{formatStatistic(item.stats.spearman)}</td>
                  <td>
                    {item.stats.pairedCount >= MIN_CORRELATION_SAMPLE_SIZE
                      ? "纳入图表"
                      : "样本不足"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <details className="statistics-details statistics-requirements">
        <summary>统计方法与适用要求</summary>
        <div>
          <p>
            先按所选变量排序并截取用户指定的样本量，再对共同有效样本执行
            log(1+x)。Pearson
            使用一阶矩完成中心化，以二阶中心矩和协方差刻画线性效应；Spearman
            使用平均秩，对极端值和单调非线性关系更稳健。
          </p>
          <ul>
            <li>
              每项 n 是实际成对完整样本数；图表只展示 n≥30 的变量对。30
              是渐近区间的最低筛选门槛， 不是统计显著性或代表性的保证。
            </li>
            <li>
              95% 区间是独立配对样本与近似二元正态条件下的 Fisher z
              近似，用于表达估计不确定性；小样本区间通常较宽，不等于“无关系”。
            </li>
            <li>
              表中二阶中心矩按 1/n
              描述当前前十样本的离散程度，不作为总体无偏方差估计。
            </li>
            <li>
              Pearson 与 Spearman 差异较大时，应优先检查极端值、非线性和并列秩。
            </li>
            <li>
              样本由所选排序变量截取得到，仍存在范围限制与选择偏差，只用于探索，不推断因果。
            </li>
          </ul>
        </div>
      </details>
    </section>
  );
}

export function MultivariateExplorer({
  data,
}: {
  data: JjwxcMultivariateResponse;
}) {
  const availableDays = data.available_days.length
    ? data.available_days
    : data.timeline.map((item) => item.day);
  const [indexed, setIndexed] = useState(false);
  const [timelineSelection, setTimelineSelection] = useState<
    JjwxcTimelineMetricName[]
  >(["favorites"]);
  const [distributionMetric, setDistributionMetric] =
    useState<JjwxcTimelineMetricName>("favorites");
  const [dateFrom, setDateFrom] = useState(availableDays[0] ?? "");
  const [dateTo, setDateTo] = useState(availableDays.at(-1) ?? "");
  const [matrixSelection, setMatrixSelection] = useState<JjwxcMetricName[]>(
    () => {
      const available = matrixMetrics
        .filter((metric) =>
          data.cohort_items.some(
            (novel) => novelMetricValue(novel, metric.key) !== null,
          ),
        )
        .map((item) => item.key);
      return available.length >= 2 ? available : ["favorites", "reviews"];
    },
  );
  const vClickCoverage = data.cohort_items.filter(
    (novel) => novel.average_v_chapter_click_count !== null,
  ).length;
  const retentionCoverage = data.cohort_items.filter(
    (novel) => novel.v_to_non_v_click_retention_basis_points !== null,
  ).length;
  const filteredTimeline = useMemo(
    () =>
      data.timeline.filter(
        (item) =>
          (!dateFrom || item.day >= dateFrom) &&
          (!dateTo || item.day <= dateTo),
      ),
    [data.timeline, dateFrom, dateTo],
  );
  const filteredNormalized = useMemo(
    () => normalizeTimelineForRange(filteredTimeline),
    [filteredTimeline],
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

  return (
    <div className="analysis-stack">
      <section className="chart-panel distribution-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">DAILY DISTRIBUTION · ROBUST VIEW</p>
            <h2>每日样本分布与头部均值</h2>
          </div>
          <span>Top 10 · Tukey 箱型图</span>
        </div>
        <div className="metric-picker" aria-label="时序分布指标">
          {timelineMetrics.map((metric) => {
            const hasDistribution = data.timeline.some(
              (point) =>
                (point.metric_distributions?.[metric.key]?.observed_count ??
                  0) > 0,
            );
            return (
              <button
                aria-pressed={distributionMetric === metric.key}
                disabled={!hasDistribution}
                key={metric.key}
                onClick={() => setDistributionMetric(metric.key)}
                type="button"
              >
                {metric.label}
              </button>
            );
          })}
        </div>
        <div className="timeline-range" aria-label="统计时间范围">
          <label>
            <span>开始日期</span>
            <input
              max={dateTo || availableDays.at(-1)}
              min={availableDays[0]}
              onChange={(event) => {
                setDateFrom(event.target.value);
                if (dateTo && event.target.value > dateTo)
                  setDateTo(event.target.value);
              }}
              type="date"
              value={dateFrom}
            />
          </label>
          <label>
            <span>结束日期</span>
            <input
              max={availableDays.at(-1)}
              min={dateFrom || availableDays[0]}
              onChange={(event) => {
                setDateTo(event.target.value);
                if (dateFrom && event.target.value < dateFrom)
                  setDateFrom(event.target.value);
              }}
              type="date"
              value={dateTo}
            />
          </label>
          <p>
            统计时间：{dateFrom || "最早"} 至 {dateTo || "最新"} ·{" "}
            {filteredTimeline.length} 个快照日
          </p>
        </div>
        <DistributionTrendChart
          metric={distributionMetric}
          timeline={filteredTimeline}
        />
        <p className="analysis-note">
          每日先保留每部作品最后一条快照，再按所选指标排序。Top 取最多 10
          部求均值并绘制折线；Bottom 均值只保留最新摘要，不绘制时序线。箱体显示
          25%、50%、75% 分位数，须线采用 1.5
          倍四分位距。须外值不再单独绘点，但不会从原始数据或 Top 10
          均值中删除。左轴只用于箱型分布，右轴只用于 Top 10
          均值，两轴独立缩放，不比较折线与箱体的垂直位置。每日采集作品集合会随榜单来源与采集成功情况变化，本图不采用固定作品队列。
        </p>
        <details className="statistics-details statistics-requirements">
          <summary>分布统计要求与解释边界</summary>
          <div>
            <ul>
              <li>
                每个统计日都显示有效样本量 n；不足 10 部时使用全部有效作品。
              </li>
              <li>Top 组不足 10 部时使用全部有效作品，只作小样本描述。</li>
              <li>
                每日作品集合可能变化，本图描述当日采集样本的截面分布，不等同于固定作品队列的增长率。
              </li>
              <li>
                四分位距 IQR = Q3 − Q1；Tukey 须线边界为 Q1 − 1.5 × IQR 与 Q3 +
                1.5 × IQR。须外值表示相对当日样本偏离较大，不等于采集错误。
              </li>
              <li>
                当新增较多低量级作品时，四分位数和须线上界会下降，原有头部作品可能集中落在须线外；解释跨日变化时必须同时查看样本量。
              </li>
              <li>
                总采集量不稳定时，中位数和四分位数通常比总和更稳健；仍应结合样本量与榜单来源解释。
              </li>
            </ul>
          </div>
        </details>
      </section>

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
          timeline={filteredTimeline}
          normalized={filteredNormalized}
          metrics={timelineSelection}
          indexed={indexed}
          label="JJWXC 多指标时间轴图（平均每部作品）"
        />
        <p className="analysis-note">
          默认显示原值与每部作品均值，并以收藏数为左侧纵轴；均值按每个快照日的实际作品数计算。
          增加变量后会分配独立纵轴，并按量级自动选用千、万或亿。
          基准指数模式把区间首个有效值设为
          100%，只比较变化速度。跨日比较仍应结合当日样本量与上方分布图解释。
        </p>
        <details className="statistics-details statistics-requirements">
          <summary>统计要求说明</summary>
          <div>
            <ul>
              <li>
                每部作品均值 = 当日有效值之和 ÷
                当日实际有快照的作品数；不再展示容易受采集数量影响的总量线。
              </li>
              <li>
                V/非 V
                点击先计算单部作品的章均点击，再对当天有点击值的作品取均值，不会重复除以作品数。
              </li>
              <li>
                缺失值保持为空且不补零；基准指数仅比较变化速度，不能替代原值规模。
              </li>
              <li>
                历史仅指本项目保存的每日快照，同一天每部作品只使用最后一条有效快照。
              </li>
            </ul>
          </div>
        </details>
        <p className="analysis-note v-click-coverage" role="status">
          V 章点击覆盖：{vClickCoverage}/{data.cohort_items.length} 部作品。 V
          章数值仅在作品作者本人授权导入后台统计时保存；公开页和普通读者登录页缺失该字段时保持为空。
          留存代理覆盖：{retentionCoverage}/{data.cohort_items.length} 部作品。
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
          {matrixMetrics.map((metric) => (
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
          所有非负计数先执行 log(1+x) 并做 Z-score 标准化，再按成对完整样本计算
          Pearson r；
          这降低了积分、点击等长尾变量的极端值影响。矩阵使用所选作品集合的最新快照。
          “V/非 V 点击留存比（代理）”按 V 章均点击 ÷ 非 V
          章均点击计算，仅纳入两侧均可见且非 V 均值大于 0
          的作品；它不是去重读者留存率，也不用于因果推断。
        </p>
      </section>

      <CorrelationSampleComparison novels={data.cohort_items} />
    </div>
  );
}
