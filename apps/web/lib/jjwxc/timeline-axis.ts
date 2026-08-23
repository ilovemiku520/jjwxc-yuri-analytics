import type { JjwxcTimelineMetricName } from "../../types/api";

export interface TimelineAxisSpec {
  metric: JjwxcTimelineMetricName;
  label: string;
  statistic: "求和统计" | "跨作品均值";
  position: "left" | "right";
  offset: number;
  divisor: number;
  displayUnit: string;
}

const metadata: Record<
  JjwxcTimelineMetricName,
  { label: string; statistic: TimelineAxisSpec["statistic"]; baseUnit: string }
> = {
  reviews: { label: "总书评", statistic: "求和统计", baseUnit: "条" },
  favorites: { label: "总收藏", statistic: "求和统计", baseUnit: "次" },
  points: { label: "总积分", statistic: "求和统计", baseUnit: "积分" },
  words: { label: "总字数", statistic: "求和统计", baseUnit: "字" },
  clicks: {
    label: "非 V 章均点击",
    statistic: "跨作品均值",
    baseUnit: "次/章",
  },
};

export function buildTimelineAxisSpecs(
  metrics: JjwxcTimelineMetricName[],
  maxima: Partial<Record<JjwxcTimelineMetricName, number>>,
): TimelineAxisSpec[] {
  return metrics.map((metric, index) => {
    const meta = metadata[metric];
    const { divisor, prefix } = compactAxisUnit(maxima[metric] ?? 0);
    return {
      metric,
      label: meta.label,
      statistic: meta.statistic,
      position: index === 0 ? "left" : "right",
      offset: index < 2 ? 0 : 76,
      divisor,
      displayUnit: `${prefix}${meta.baseUnit}`,
    };
  });
}

export function compactAxisUnit(maximum: number): {
  divisor: number;
  prefix: string;
} {
  const absolute = Math.abs(maximum);
  if (absolute >= 100_000_000) return { divisor: 100_000_000, prefix: "亿" };
  if (absolute >= 10_000) return { divisor: 10_000, prefix: "万" };
  if (absolute >= 1_000) return { divisor: 1_000, prefix: "千" };
  return { divisor: 1, prefix: "" };
}

export function formatAxisTick(value: number, divisor: number) {
  const scaled = value / divisor;
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(
    scaled,
  );
}
