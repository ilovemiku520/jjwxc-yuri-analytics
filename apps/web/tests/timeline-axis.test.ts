import { describe, expect, it } from "vitest";

import {
  buildTimelineAxisSpecs,
  compactAxisUnit,
  formatAxisTick,
} from "../lib/jjwxc/timeline-axis";

describe("JJWXC timeline axis planning", () => {
  it("chooses readable Chinese compact units from observed magnitude", () => {
    expect(compactAxisUnit(4_620)).toEqual({ divisor: 1_000, prefix: "千" });
    expect(compactAxisUnit(45_100)).toEqual({ divisor: 10_000, prefix: "万" });
    expect(compactAxisUnit(528_600_000)).toEqual({
      divisor: 100_000_000,
      prefix: "亿",
    });
    expect(formatAxisTick(17_300, 1_000)).toBe("17.3");
  });

  it("assigns three selected statistics to left, right, and offset-right axes", () => {
    const axes = buildTimelineAxisSpecs(["reviews", "favorites", "clicks"], {
      reviews: 17_300,
      favorites: 193_000,
      clicks: 16_933.33,
    });

    expect(axes.map((axis) => [axis.position, axis.offset])).toEqual([
      ["left", 0],
      ["right", 0],
      ["right", 76],
    ]);
    expect(axes[0]).toMatchObject({
      displayUnit: "万条",
      statistic: "求和统计",
    });
    expect(axes[2]).toMatchObject({
      displayUnit: "万次/章",
      statistic: "跨作品均值",
    });
  });
});
