import { describe, expect, it } from "vitest";
import { computePaddedRange, formatAxisValue } from "./mlCurve";

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
