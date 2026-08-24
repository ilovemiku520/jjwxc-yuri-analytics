"use client";

import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
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
  JjwxcNovel,
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
  BarChart,
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
  { key: "synopsis_chars", label: "文案字符数" },
];

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
  if (metric === "reviews") return point.total_review_count;
  if (metric === "favorites") return point.total_favorite_count;
  if (metric === "points") return point.total_points;
  if (metric === "words") return point.total_word_count;
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

function novelMetricValue(novel: JjwxcNovel, metric: JjwxcMetricName): number | null {
  if (metric === "reviews") return novel.review_count;
  if (metric === "favorites") return novel.favorite_count;
  if (metric === "points") return novel.points;
  if (metric === "words") return novel.word_count;
  if (metric === "clicks") return novel.average_non_v_chapter_click_count;
  if (metric === "v_clicks") return novel.average_v_chapter_click_count;
  return novel.synopsis_char_count;
}

function logStandardizedPearson(pairs: Array<[number, number]>): number | null {
  if (pairs.length < 2) return null;
  const transformed = pairs.map(([x, y]) => [Math.log1p(x), Math.log1p(y)] as const);
  const xMean = transformed.reduce((sum, [x]) => sum + x, 0) / transformed.length;
  const yMean = transformed.reduce((sum, [, y]) => sum + y, 0) / transformed.length;
  const numerator = transformed.reduce(
    (sum, [x, y]) => sum + (x - xMean) * (y - yMean),
    0,
  );
  const xScale = Math.sqrt(
    transformed.reduce((sum, [x]) => sum + (x - xMean) ** 2, 0),
  );
  const yScale = Math.sqrt(
    transformed.reduce((sum, [, y]) => sum + (y - yMean) ** 2, 0),
  );
  if (xScale === 0 || yScale === 0) return null;
  return Math.max(-1, Math.min(1, numerator / (xScale * yScale)));
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

function TopTenCorrelationComparison({ novels }: { novels: JjwxcNovel[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [rankingMetric, setRankingMetric] = useState<JjwxcMetricName>("favorites");
  const topNovels = useMemo(
    () =>
      [...novels]
        .filter((novel) => novelMetricValue(novel, rankingMetric) !== null)
        .sort(
          (left, right) =>
            (novelMetricValue(right, rankingMetric) ?? 0) -
              (novelMetricValue(left, rankingMetric) ?? 0) ||
            left.novel_id.localeCompare(right.novel_id),
        )
        .slice(0, 10),
    [novels, rankingMetric],
  );
  const comparisons = useMemo(
    () =>
      allMetrics
        .filter((metric) => metric.key !== rankingMetric)
        .map((metric) => {
          const pairs = topNovels.flatMap((novel) => {
            const x = novelMetricValue(novel, rankingMetric);
            const y = novelMetricValue(novel, metric.key);
            return x === null || y === null ? [] : ([[x, y]] as Array<[number, number]>);
          });
          return {
            metric: metric.key,
            label: metric.label,
            pairedCount: pairs.length,
            coefficient: logStandardizedPearson(pairs),
          };
        })
        .filter((item) => item.coefficient !== null),
    [rankingMetric, topNovels],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    chart.setOption({
      animationDuration: 250,
      grid: { left: 155, right: 58, top: 20, bottom: 38 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "value",
        min: -1,
        max: 1,
        name: `与${labelFor(rankingMetric)}的 Pearson r`,
        nameTextStyle: { color: "#b9adb6" },
        axisLabel: { color: "#b9adb6" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } },
      },
      yAxis: {
        type: "category",
        data: comparisons.map((item) => `${item.label} · n=${item.pairedCount}`),
        axisLabel: { color: "#b9adb6" },
      },
      series: [
        {
          type: "bar",
          data: comparisons.map((item) => ({
            value: Number(item.coefficient?.toFixed(3)),
            itemStyle: {
              color: (item.coefficient ?? 0) >= 0 ? "#f28e5b" : "#3a7bbf",
              borderRadius: (item.coefficient ?? 0) >= 0 ? [0, 6, 6, 0] : [6, 0, 0, 6],
            },
          })),
          label: { show: true, position: "right", color: "#f7f3f6" },
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [comparisons, rankingMetric]);

  return (
    <section className="chart-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">TOP 10 COHORT · ADJUSTABLE VARIABLE</p>
          <h2>榜单前十作品相关系数比较</h2>
        </div>
        <span>蓝色负相关 · 橙色正相关</span>
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
        aria-label={`按${labelFor(rankingMetric)}选出的前十作品相关系数比较图`}
        className="analysis-chart top-ten-correlation-chart"
        ref={containerRef}
        role="img"
      />
      <p className="top-ten-cohort-names">
        当前样本：{topNovels.map((novel) => novel.title).join("、") || "没有足够数据"}
      </p>
      <p className="analysis-note">
        先按所选变量取前十部作品，再在该样本内对各变量执行 log(1+x)、Z-score
        标准化和成对完整 Pearson 相关；每根柱的 n 是实际共同有效样本数。
      </p>
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
  const [dateFrom, setDateFrom] = useState(availableDays[0] ?? "");
  const [dateTo, setDateTo] = useState(availableDays.at(-1) ?? "");
  const [matrixSelection, setMatrixSelection] = useState<JjwxcMetricName[]>(
    allMetrics.map((item) => item.key),
  );
  const vClickCoverage = data.cohort_items.filter(
    (novel) => novel.average_v_chapter_click_count !== null,
  ).length;
  const filteredTimeline = useMemo(
    () =>
      data.timeline.filter(
        (item) => (!dateFrom || item.day >= dateFrom) && (!dateTo || item.day <= dateTo),
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
        <div className="timeline-range" aria-label="统计时间范围">
          <label>
            <span>开始日期</span>
            <input
              max={dateTo || availableDays.at(-1)}
              min={availableDays[0]}
              onChange={(event) => {
                setDateFrom(event.target.value);
                if (dateTo && event.target.value > dateTo) setDateTo(event.target.value);
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
                if (dateFrom && event.target.value < dateFrom) setDateFrom(event.target.value);
              }}
              type="date"
              value={dateTo}
            />
          </label>
          <p>
            统计时间：{dateFrom || "最早"} 至 {dateTo || "最新"} · {filteredTimeline.length}
            个快照日 · {data.cohort_items.length} 部作品
          </p>
        </div>
        <TimelineChart
          timeline={filteredTimeline}
          normalized={filteredNormalized}
          metrics={timelineSelection}
          indexed={indexed}
          label="JJWXC 多指标时间轴图"
        />
        <p className="analysis-note">
          默认显示原值并以收藏数为左侧纵轴；增加变量后会分配独立纵轴，并按量级自动选用千、万或亿。
          基准指数模式把区间首个有效值设为 100%，只比较变化速度。
        </p>
        <p className="analysis-note v-click-coverage" role="status">
          V 章点击覆盖：{vClickCoverage}/{data.cohort_items.length} 部作品。
          V 章数值只在已登录作品页提供时保存；公开点击接口缺失该字段时不会再覆盖登录页中的原值。
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
          所有非负计数先执行 log(1+x) 并做 Z-score 标准化，再按成对完整样本计算 Pearson r；
          这降低了积分、点击等长尾变量的极端值影响。矩阵使用所选作品集合的最新快照。
        </p>
      </section>

      <TopTenCorrelationComparison novels={data.cohort_items} />
    </div>
  );
}
