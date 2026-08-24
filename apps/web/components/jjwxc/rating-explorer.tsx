"use client";

import { RadarChart } from "echarts/charts";
import {
  LegendComponent,
  RadarComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";

import { formatCount } from "../../lib/format/number";
import type {
  JjwxcAuthorRatingMetric,
  JjwxcRatingGrade,
  JjwxcRatingMetric,
  JjwxcRatingResponse,
} from "../../types/api";

echarts.use([
  RadarChart,
  RadarComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

type MetricKey = JjwxcRatingMetric | JjwxcAuthorRatingMetric;
type MetricConfig = { key: MetricKey; label: string };
type DisplayItem = {
  entity_id: string;
  title: string;
  author_display_name: string;
  score_basis_points: number;
  grade: JjwxcRatingGrade;
  coverage_basis_points: number;
  component_scores: Partial<Record<MetricKey, number | null>>;
  raw_values?: Partial<Record<MetricKey, number | null>>;
};

const novelMetrics: MetricConfig[] = [
  { key: "favorites", label: "收藏" },
  { key: "reviews", label: "书评" },
  { key: "points", label: "积分" },
  { key: "clicks", label: "非 V 章均点击" },
  { key: "words", label: "字数" },
];
const authorMetrics: MetricConfig[] = [
  { key: "nonlocked_works", label: "非锁定作品" },
  { key: "author_favorites", label: "作者收藏" },
  { key: "work_favorites", label: "作品总收藏" },
  { key: "words", label: "写文总字数" },
  { key: "points", label: "总积分" },
];

type EntityKind = "novels" | "authors";

function gradeFor(score: number): JjwxcRatingGrade {
  if (score >= 9000) return "SSS";
  if (score >= 8000) return "SS";
  if (score >= 6500) return "S";
  if (score >= 4500) return "A";
  return "B";
}

function normalizeWeights(
  weights: Partial<Record<MetricKey, number>>,
  metrics: MetricConfig[],
): Record<MetricKey, number> {
  const total = metrics.reduce((sum, metric) => sum + (weights[metric.key] ?? 0), 0);
  if (total <= 0) {
    return Object.fromEntries(
      metrics.map((metric) => [metric.key, weights[metric.key] ?? 0]),
    ) as Record<MetricKey, number>;
  }
  return Object.fromEntries(
    metrics.map((metric) => [
      metric.key,
      ((weights[metric.key] ?? 0) * 10000) / total,
    ]),
  ) as Record<MetricKey, number>;
}

function rescore(
  items: DisplayItem[],
  rawWeights: Partial<Record<MetricKey, number>>,
  metrics: MetricConfig[],
  kind: EntityKind,
) {
  const weights = normalizeWeights(rawWeights, metrics);
  return items
    .map((item) => {
      const observed = metrics.filter(
        (metric) =>
          item.component_scores[metric.key] !== null && weights[metric.key] > 0,
      );
      const observedWeight = observed.reduce(
        (sum, metric) => sum + weights[metric.key],
        0,
      );
      const score = observedWeight
        ? observed.reduce(
            (sum, metric) =>
              sum +
              (item.component_scores[metric.key] ?? 0) * weights[metric.key],
            0,
          ) / observedWeight
        : 0;
      const coverageFactor =
        kind === "authors" ? item.coverage_basis_points / 10000 : 1;
      const rounded = Math.round(score * coverageFactor);
      return { ...item, score_basis_points: rounded, grade: gradeFor(rounded) };
    })
    .sort(
      (left, right) =>
        right.score_basis_points - left.score_basis_points ||
        left.entity_id.localeCompare(right.entity_id),
    );
}

function RatingRadar({ item, metrics }: { item: DisplayItem; metrics: MetricConfig[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    chart.setOption({
      color: ["#ffb5d2"],
      tooltip: { trigger: "item" },
      radar: {
        radius: "66%",
        indicator: metrics.map((metric) => ({ name: metric.label, max: 100 })),
        axisName: { color: "#b9adb6" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.12)" } },
        splitArea: { areaStyle: { color: ["transparent", "rgba(255,255,255,.02)"] } },
        axisLine: { lineStyle: { color: "rgba(255,255,255,.12)" } },
      },
      series: [
        {
          type: "radar",
          name: item.title,
          data: [
            {
              value: metrics.map(
                (metric) => (item.component_scores[metric.key] ?? 0) / 100,
              ),
              name: item.title,
              areaStyle: { color: "rgba(241,139,184,.25)" },
            },
          ],
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [item, metrics]);

  return (
    <div
      className="rating-radar"
      ref={containerRef}
      role="img"
      aria-label={`${item.title}公开数据表现雷达图`}
    />
  );
}

export function RatingExplorer({ data }: { data: JjwxcRatingResponse }) {
  const [kind, setKind] = useState<EntityKind>("novels");
  const [day, setDay] = useState(data.selected_day);
  const [novelWeights, setNovelWeights] = useState<Partial<Record<MetricKey, number>>>(
    data.default_weights,
  );
  const [authorWeights, setAuthorWeights] = useState<Partial<Record<MetricKey, number>>>(
    data.author_default_weights,
  );
  const metrics = kind === "novels" ? novelMetrics : authorMetrics;
  const weights = kind === "novels" ? novelWeights : authorWeights;
  const sourceItems: DisplayItem[] = kind === "novels" ? data.novels : data.authors;
  const ranked = useMemo(
    () => rescore(sourceItems, weights, metrics, kind),
    [kind, metrics, sourceItems, weights],
  );
  const [selectedId, setSelectedId] = useState(ranked[0]?.entity_id ?? "");
  const selected = ranked.find((item) => item.entity_id === selectedId) ?? ranked[0];
  const normalized = normalizeWeights(weights, metrics);

  function updateWeight(metric: MetricKey, value: number) {
    if (kind === "novels") {
      setNovelWeights((current) => ({ ...current, [metric]: value }));
    } else {
      setAuthorWeights((current) => ({ ...current, [metric]: value }));
    }
  }

  return (
    <section className="chart-panel rating-panel" aria-labelledby="rating-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">ADJUSTABLE COHORT RATING · SSS—B</p>
          <h2 id="rating-title">作品与作者公开数据表现评级</h2>
        </div>
        <span>相对同批样本，不代表文学质量</span>
      </div>

      <div className="rating-toolbar">
        <div className="rating-tabs" aria-label="评级对象">
          <button
            type="button"
            aria-pressed={kind === "novels"}
            onClick={() => setKind("novels")}
          >
            作品
          </button>
          <button
            type="button"
            aria-pressed={kind === "authors"}
            onClick={() => setKind("authors")}
          >
            作者
          </button>
        </div>
        <label className="rating-day">
          <span>统计时间</span>
          <select value={day} onChange={(event) => setDay(event.target.value)}>
            {data.available_days.map((availableDay) => (
              <option key={availableDay} value={availableDay}>
                {availableDay}
              </option>
            ))}
          </select>
        </label>
        <button
          className="reset-weights"
          type="button"
          onClick={() =>
            kind === "novels"
              ? setNovelWeights(data.default_weights)
              : setAuthorWeights(data.author_default_weights)
          }
        >
          恢复数据校准权重
        </button>
      </div>

      <div className="weight-grid">
        {metrics.map((metric) => (
          <label key={metric.key}>
            <span>
              {metric.label}
              <strong>{(normalized[metric.key] / 100).toFixed(1)}%</strong>
            </span>
            <input
              aria-label={`${metric.label}权重`}
              type="range"
              min={0}
              max={10000}
              step={100}
              value={weights[metric.key]}
              onChange={(event) =>
                updateWeight(metric.key, Number(event.target.value))
              }
            />
          </label>
        ))}
      </div>

      <div className="rating-grid">
        <div className="rating-ranking" aria-label={`${kind === "novels" ? "作品" : "作者"}评分排行`}>
          {ranked.map((item, index) => (
            <button
              key={item.entity_id}
              type="button"
              aria-pressed={selected?.entity_id === item.entity_id}
              onClick={() => setSelectedId(item.entity_id)}
            >
              <span className="rank-number">{String(index + 1).padStart(2, "0")}</span>
              <span>
                <strong>{item.title}</strong>
                <small>
                  {kind === "novels" ? item.author_display_name : `${item.coverage_basis_points / 100}% 数据覆盖`}
                </small>
              </span>
              <span className={`rating-grade grade-${item.grade.toLowerCase()}`}>
                {item.grade}
              </span>
              <span>{(item.score_basis_points / 100).toFixed(1)}</span>
            </button>
          ))}
        </div>
        {selected ? (
          <div className="radar-panel">
            <div>
              <p className="eyebrow">FIVE-DIMENSION PROFILE</p>
              <h3>{selected.title}</h3>
              <p>
                综合分 {(selected.score_basis_points / 100).toFixed(1)} · {selected.grade} · 数据覆盖 {selected.coverage_basis_points / 100}%
              </p>
            </div>
            {kind === "authors" && selected.raw_values ? (
              <dl className="author-radar-values">
                {authorMetrics.map((metric) => (
                  <div key={metric.key}>
                    <dt>{metric.label}</dt>
                    <dd>
                      {selected.raw_values?.[metric.key] === null ||
                      selected.raw_values?.[metric.key] === undefined
                        ? "待专栏采集"
                        : formatCount(selected.raw_values[metric.key] ?? 0)}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
            <RatingRadar item={selected} metrics={metrics} />
          </div>
        ) : null}
      </div>

      <p className="analysis-note">
        默认权重 = 产品含义先验 × 覆盖率、变异系数与相关冗余修正；指标先取 log(1+x)
        后转为同批样本百分位。等级阈值为 SSS ≥ 90、SS ≥ 80、S ≥ 65、A ≥ 45、其余 B。
        当前只有一个已保存日期；每日快照累积后，统计时间会自动出现更多可选日期。
      </p>
    </section>
  );
}
