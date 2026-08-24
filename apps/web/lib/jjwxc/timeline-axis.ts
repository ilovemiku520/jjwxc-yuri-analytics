import type { JjwxcTimelineMetricName } from "../../types/api";

export type TimelineAggregation = "total" | "per_work";

export interface TimelineAxisSpec {
  metric: JjwxcTimelineMetricName;
  label: string;
  statistic: "求和统计" | "每部作品均值" | "跨作品章均值";
  position: "left" | "right";
  offset: number;
  divisor: number;
  displayUnit: string;
}

const metadata: Record<
  JjwxcTimelineMetricName,
  {
    totalLabel: string;
    averageLabel: string;
    totalUnit: string;
    averageUnit: string;
    inherentlyAveraged: boolean;
  }
> = {
  reviews: {
    totalLabel: "总书评",
    averageLabel: "每部作品平均书评",
    totalUnit: "条",
    averageUnit: "条/部",
    inherentlyAveraged: false,
  },
  favorites: {
    totalLabel: "总收藏",
    averageLabel: "每部作品平均收藏",
    totalUnit: "次",
    averageUnit: "次/部",
    inherentlyAveraged: false,
  },
  points: {
    totalLabel: "总积分",
    averageLabel: "每部作品平均积分",
    totalUnit: "积分",
    averageUnit: "积分/部",
    inherentlyAveraged: false,
  },
  words: {
    totalLabel: "总字数",
    averageLabel: "每部作品平均字数",
    totalUnit: "字",
    averageUnit: "字/部",
    inherentlyAveraged: false,
  },
  clicks: {
    totalLabel: "非 V 章均点击",
    averageLabel: "非 V 章均点击",
    totalUnit: "次/章",
    averageUnit: "次/章",
    inherentlyAveraged: true,
  },
  v_clicks: {
    totalLabel: "V 章均点击",
    averageLabel: "V 章均点击",
    totalUnit: "次/章",
    averageUnit: "次/章",
    inherentlyAveraged: true,
  },
};

export function buildTimelineAxisSpecs(
  metrics: JjwxcTimelineMetricName[],
  maxima: Partial<Record<JjwxcTimelineMetricName, number>>,
  aggregation: TimelineAggregation = "total",
): TimelineAxisSpec[] {
  return metrics.map((metric, index) => {
    const meta = metadata[metric];
    const { divisor, prefix } = compactAxisUnit(maxima[metric] ?? 0);
    const useAverage = aggregation === "per_work" && !meta.inherentlyAveraged;
    return {
      metric,
      label: useAverage ? meta.averageLabel : meta.totalLabel,
      statistic: meta.inherentlyAveraged
        ? "跨作品章均值"
        : useAverage
          ? "每部作品均值"
          : "求和统计",
      position: index === 0 ? "left" : "right",
      offset: index < 2 ? 0 : 76,
      divisor,
      displayUnit: `${prefix}${useAverage ? meta.averageUnit : meta.totalUnit}`,
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
