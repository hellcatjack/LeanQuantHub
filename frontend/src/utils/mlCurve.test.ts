import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  buildMinorTickIndices,
  buildTickIndices,
  buildMinorTickValues,
  computePaddedRange,
  formatAxisValue,
} from "./mlCurve";

describe("computePaddedRange", () => {
  it("adds padding when values are flat", () => {
    const res = computePaddedRange([0.123, 0.123]);
    expect(res).not.toBeNull();
    expect(res!.max).toBeGreaterThan(res!.min);
  });
});

describe("formatAxisValue", () => {
  it("adds more precision for small spans", () => {
    expect(formatAxisValue(0.123456, 0.005)).toBe("0.12346");
  });
});

describe("buildTickIndices", () => {
  it("caps tick count by total length and keeps ends", () => {
    expect(buildTickIndices(3, 5)).toEqual([0, 1, 2]);
  });

  it("returns evenly spaced major ticks", () => {
    const ticks = buildTickIndices(10, 5);
    expect(ticks).toHaveLength(5);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBe(9);
  });
});

describe("buildMinorTickIndices", () => {
  it("adds midpoint ticks between major ticks", () => {
    expect(buildMinorTickIndices(10, [0, 4, 9])).toEqual([2, 7]);
  });
});

describe("buildMinorTickValues", () => {
  it("adds mid values between major values", () => {
    expect(buildMinorTickValues([0, 1, 2])).toEqual([0.5, 1.5]);
  });
});

describe("ml curve styles", () => {
  it("shrinks axis and marker label fonts", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    const axisStart = css.indexOf(".ml-curve-axis-label");
    const bestStart = css.indexOf(".ml-curve-best-label");
    const axisBlock =
      axisStart >= 0 ? css.slice(axisStart, axisStart + 200) : "";
    const bestBlock =
      bestStart >= 0 ? css.slice(bestStart, bestStart + 200) : "";
    expect(axisBlock).toContain("font-size: 8px");
    expect(bestBlock).toContain("font-size: 9px");
  });

  it("defines minor vertical gridline style", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    expect(css).toContain(".ml-curve-grid-line.vertical.minor");
  });

  it("defines minor horizontal gridline style", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
    expect(css).toContain(".ml-curve-grid-line.minor");
    expect(css).toContain("stroke: #cbd5e1");
    expect(css).toContain("opacity: 0.8");
  });
});
