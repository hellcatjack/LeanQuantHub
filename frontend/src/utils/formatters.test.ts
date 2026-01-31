import { describe, expect, it } from "vitest";

import { formatRealizedPnlValue } from "./formatters";


describe("formatRealizedPnlValue", () => {
  it("returns fallback for nullish", () => {
    expect(formatRealizedPnlValue(null, "--")).toBe("--");
    expect(formatRealizedPnlValue(undefined, "--")).toBe("--");
  });

  it("formats numeric values to 2 decimals", () => {
    expect(formatRealizedPnlValue(1.2345, "--")).toBe("1.23");
  });
});
