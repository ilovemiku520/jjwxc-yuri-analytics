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

  it("assigns per-work statistics to left, right, and offset-right axes", () => {
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
      label: "每部作品平均书评",
      displayUnit: "万条/部",
      statistic: "每部作品均值",
    });
    expect(axes[2]).toMatchObject({
      displayUnit: "万次/章",
      statistic: "跨作品章均值",
    });
  });

  it("labels per-work averages without dividing already averaged click metrics twice", () => {
    const axes = buildTimelineAxisSpecs(["favorites", "reviews", "clicks"], {
      favorites: 32_000,
      reviews: 1_260,
      clicks: 18_200,
    });

    expect(axes[0]).toMatchObject({
      label: "每部作品平均收藏",
      statistic: "每部作品均值",
      displayUnit: "万次/部",
    });
    expect(axes[2]).toMatchObject({
      label: "非 V 章均点击",
      statistic: "跨作品章均值",
      displayUnit: "万次/章",
    });
  });
});
