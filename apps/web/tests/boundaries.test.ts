import { describe, expect, it } from "vitest";

import { validatedApiOrigin, validatedApiPath } from "../lib/api/boundary";
import { trendDateRange, trendSeries } from "../lib/chart/trend";
import {
  allowedSearchValue,
  boundedIntegerSearchValue,
  firstSearchValue,
  pageHref,
  safeRouteSegment,
} from "../lib/url/search";

describe("private API boundary", () => {
  it("accepts only the reviewed local, Compose, and Railway private origins", () => {
    expect(validatedApiOrigin()).toBe("http://127.0.0.1:8000");
    expect(validatedApiOrigin("http://api:8000")).toBe("http://api:8000");
    expect(validatedApiOrigin("http://api.railway.internal:8000")).toBe(
      "http://api.railway.internal:8000",
    );
    for (const rejected of [
      "https://example.com",
      "http://user:secret@api:8000",
      "http://api:8000/private",
      "http://api:8000?token=secret",
      "https://api.railway.internal:8000",
      "http://railway.internal.evil.example:8000",
    ]) {
      expect(() => validatedApiOrigin(rejected)).toThrow(/private API boundary/u);
    }
  });

  it("accepts only bounded v1 relative read paths", () => {
    expect(validatedApiPath("/api/v1/works?limit=20")).toBe("/api/v1/works?limit=20");
    for (const rejected of [
      "/health/live",
      "https://example.com/api/v1/works",
      "/api/v1/works#fragment",
      "/api/v1/works\\escape",
      "/api/v1/works\nsecret",
      `/api/v1/${"a".repeat(2_100)}`,
    ]) {
      expect(() => validatedApiPath(rejected)).toThrow(/versioned relative/u);
    }
  });
});

describe("URL state boundary", () => {
  it("normalizes scalar values and rejects unsafe or oversized state", () => {
    expect(firstSearchValue(["  yuri  ", "ignored"])).toBe("yuri");
    expect(firstSearchValue(" ")).toBeUndefined();
    expect(firstSearchValue("a".repeat(101), 100)).toBeUndefined();
    expect(firstSearchValue("bad\nvalue")).toBeUndefined();
    expect(allowedSearchValue("open", ["open", "resolved"] as const)).toBe("open");
    expect(allowedSearchValue("secret", ["open", "resolved"] as const)).toBeUndefined();
  });

  it("builds encoded local pagination URLs", () => {
    expect(pageHref("/works", { q: "百合 花", cursor: "a+b=" })).toBe(
      "/works?q=%E7%99%BE%E5%90%88+%E8%8A%B1&cursor=a%2Bb%3D",
    );
    expect(() => pageHref("//example.com", {})).toThrow(/local/u);
    expect(safeRouteSegment("work-1")).toBe("work-1");
    expect(safeRouteSegment("bad/segment")).toBeNull();
  });

  it("accepts only bounded integer query state", () => {
    expect(boundedIntegerSearchValue("25", 1, 200, 50)).toBe(25);
    expect(boundedIntegerSearchValue(["100", "2"], 1, 200, 50)).toBe(100);
    for (const rejected of ["0", "201", "1.5", "-1", "1e2", "bad"]) {
      expect(boundedIntegerSearchValue(rejected, 1, 200, 50)).toBe(50);
    }
  });
});

describe("trend projection", () => {
  it("derives a seven-day UTC window and chart series", () => {
    expect(trendDateRange("2026-08-22T03:00:00Z")).toEqual({
      dateFrom: "2026-08-16",
      dateTo: "2026-08-22",
    });
    expect(
      trendSeries([
        {
          day: "2026-08-22",
          total_public_bookmark_count: 8,
          total_public_like_count: 12,
        },
      ]),
    ).toEqual({ days: ["2026-08-22"], likes: [12], bookmarks: [8] });
  });

  it("preserves missing author metrics instead of drawing false zeroes", () => {
    expect(
      trendSeries([
        {
          day: "2026-08-23",
          total_public_bookmark_count: null,
          total_public_like_count: null,
        },
      ]),
    ).toEqual({ days: ["2026-08-23"], likes: [null], bookmarks: [null] });
  });
});
