export interface MetricTrendPoint {
  day: string;
  total_public_bookmark_count: number | null;
  total_public_like_count: number | null;
}

export interface TrendSeries {
  days: string[];
  likes: Array<number | null>;
  bookmarks: Array<number | null>;
}

export function trendSeries(items: MetricTrendPoint[]): TrendSeries {
  return {
    days: items.map((item) => item.day),
    likes: items.map((item) => item.total_public_like_count),
    bookmarks: items.map((item) => item.total_public_bookmark_count),
  };
}

export function trendDateRange(latestObservedAt: string | null): {
  dateFrom: string;
  dateTo: string;
} | null {
  if (!latestObservedAt) {
    return null;
  }
  const latest = new Date(latestObservedAt);
  if (Number.isNaN(latest.valueOf())) {
    return null;
  }
  const start = new Date(latest);
  start.setUTCDate(start.getUTCDate() - 6);
  return {
    dateFrom: start.toISOString().slice(0, 10),
    dateTo: latest.toISOString().slice(0, 10),
  };
}
