import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatCard } from "../components/ui/stat-card";
import {
  formatBasisPoints,
  formatCount,
  formatScaledCount,
  formatSignedCount,
} from "../lib/format/number";

describe("Phase 3 dashboard primitives", () => {
  it("renders a semantic statistic card", () => {
    render(<StatCard label="作品" value="1,024" note="已验证目录记录" />);
    expect(screen.getByText("作品")).toBeInTheDocument();
    expect(screen.getByText("1,024")).toBeInTheDocument();
  });

  it("formats only non-negative safe integer counts", () => {
    expect(formatCount(12345)).toBe("12,345");
    expect(formatCount(-1)).toBe("—");
    expect(formatCount(Number.POSITIVE_INFINITY)).toBe("—");
  });

  it("formats signed cohort changes and basis-point rates", () => {
    expect(formatSignedCount(1200)).toBe("+1,200");
    expect(formatSignedCount(-5)).toBe("−5");
    expect(formatSignedCount(null)).toBe("—");
    expect(formatBasisPoints(667)).toBe("+6.67%");
    expect(formatBasisPoints(-833)).toBe("-8.33%");
    expect(formatBasisPoints(null)).toBe("—");
  });

  it("formats integer and centi-unit ranking scores without floating drift", () => {
    expect(formatScaledCount(10900, 100)).toBe("109");
    expect(formatScaledCount(6833, 100)).toBe("68.33");
    expect(formatScaledCount(12, 1)).toBe("12");
    expect(formatScaledCount(-1, 100)).toBe("—");
  });
});
