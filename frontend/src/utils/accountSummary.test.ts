import { describe, expect, it } from "vitest";
import { resolveAccountSummaryLabel } from "./accountSummary";

describe("resolveAccountSummaryLabel", () => {
  it("returns mapped label when exists", () => {
    const map = { NetLiquidation: "净清算值" };
    expect(resolveAccountSummaryLabel("NetLiquidation", map)).toBe("净清算值");
  });

  it("falls back to key when missing", () => {
    expect(resolveAccountSummaryLabel("UnknownTag", {})).toBe("UnknownTag");
  });

  it("falls back when map is not an object", () => {
    expect(resolveAccountSummaryLabel("NetLiquidation", "bad" as any)).toBe("NetLiquidation");
  });
});
