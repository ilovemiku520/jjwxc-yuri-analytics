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

import type {
  JjwxcRatingGrade,
  JjwxcRatingItem,
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

const metrics: Array<{ key: JjwxcRatingMetric; label: string }> = [
  { key: "favorites", label: "收藏" },
  { key: "reviews", label: "书评" },
  { key: "points", label: "积分" },
  { key: "clicks", label: "非 V 章均点击" },
  { key: "words", label: "字数" },
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
  weights: Record<JjwxcRatingMetric, number>,
): Record<JjwxcRatingMetric, number> {
  const total = metrics.reduce((sum, metric) => sum + weights[metric.key], 0);
  if (total <= 0) return weights;
  return Object.fromEntries(
    metrics.map((metric) => [metric.key, (weights[metric.key] * 10000) / total]),
  ) as Record<JjwxcRatingMetric, number>;
}

function rescore(
  items: JjwxcRatingItem[],
  rawWeights: Record<JjwxcRatingMetric, number>,
) {
  const weights = normalizeWeights(rawWeights);
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
      const rounded = Math.round(score);
      return { ...item, score_basis_points: rounded, grade: gradeFor(rounded) };
    })
    .sort(
      (left, right) =>
        right.score_basis_points - left.score_basis_points ||
        left.entity_id.localeCompare(right.entity_id),
    );
}

function RatingRadar({ item }: { item: JjwxcRatingItem }) {
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
  }, [item]);

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
  const [weights, setWeights] = useState(data.default_weights);
  const sourceItems = kind === "novels" ? data.novels : data.authors;
  const ranked = useMemo(() => rescore(sourceItems, weights), [sourceItems, weights]);
  const [selectedId, setSelectedId] = useState(ranked[0]?.entity_id ?? "");
  const selected = ranked.find((item) => item.entity_id === selectedId) ?? ranked[0];
  const normalized = normalizeWeights(weights);

  function updateWeight(metric: JjwxcRatingMetric, value: number) {
    setWeights((current) => ({ ...current, [metric]: value }));
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
          onClick={() => setWeights(data.default_weights)}
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
            <RatingRadar item={selected} />
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
