import type { JjwxcTimelineMetricName } from "../../types/api";

export interface TimelineAxisSpec {
  metric: JjwxcTimelineMetricName;
  label: string;
  statistic: "每部作品均值" | "跨作品章均值";
  position: "left" | "right";
  offset: number;
  divisor: number;
  displayUnit: string;
}

const metadata: Record<
  JjwxcTimelineMetricName,
  {
    label: string;
    unit: string;
    inherentlyAveraged: boolean;
  }
> = {
  reviews: {
    label: "每部作品平均书评",
    unit: "条/部",
    inherentlyAveraged: false,
  },
  favorites: {
    label: "每部作品平均收藏",
    unit: "次/部",
    inherentlyAveraged: false,
  },
  points: {
    label: "每部作品平均积分",
    unit: "积分/部",
    inherentlyAveraged: false,
  },
  words: {
    label: "每部作品平均字数",
    unit: "字/部",
    inherentlyAveraged: false,
  },
  clicks: {
    label: "非 V 章均点击",
    unit: "次/章",
    inherentlyAveraged: true,
  },
  v_clicks: {
    label: "V 章均点击",
    unit: "次/章",
    inherentlyAveraged: true,
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
      statistic: meta.inherentlyAveraged ? "跨作品章均值" : "每部作品均值",
      position: index === 0 ? "left" : "right",
      offset: index < 2 ? 0 : 76,
      divisor,
      displayUnit: `${prefix}${meta.unit}`,
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
