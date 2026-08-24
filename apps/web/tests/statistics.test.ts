import { describe, expect, it } from "vitest";

import { analyzeLogMomentCorrelation } from "../lib/jjwxc/statistics";

describe("JJWXC exploratory correlation statistics", () => {
  it("reports first moments, second central moments, and covariance on log counts", () => {
    const result = analyzeLogMomentCorrelation([
      [0, 0],
      [Math.E - 1, Math.E ** 2 - 1],
      [Math.E ** 2 - 1, Math.E ** 4 - 1],
      [Math.E ** 3 - 1, Math.E ** 6 - 1],
    ]);

    expect(result.pairedCount).toBe(4);
    expect(result.xMean).toBeCloseTo(1.5);
    expect(result.yMean).toBeCloseTo(3);
    expect(result.xSecondCentralMoment).toBeCloseTo(1.25);
    expect(result.ySecondCentralMoment).toBeCloseTo(5);
    expect(result.covariance).toBeCloseTo(2.5);
    expect(result.pearson).toBeCloseTo(1);
    expect(result.spearman).toBeCloseTo(1);
    expect(result.pearsonConfidenceLow).not.toBeNull();
  });

  it("uses average ranks so a monotonic nonlinear relation remains visible", () => {
    const result = analyzeLogMomentCorrelation([
      [1, 1],
      [2, 4],
      [3, 9],
      [4, 16],
      [5, 25],
    ]);

    expect(result.spearman).toBeCloseTo(1);
    expect(result.pearson).not.toBeNull();
    expect(result.pearson).toBeLessThan(1);
  });

  it("keeps uncertainty unavailable when fewer than four paired values exist", () => {
    const result = analyzeLogMomentCorrelation([
      [10, 30],
      [20, 40],
      [30, 80],
    ]);

    expect(result.pairedCount).toBe(3);
    expect(result.pearsonConfidenceLow).toBeNull();
    expect(result.pearsonConfidenceHigh).toBeNull();
  });
});
