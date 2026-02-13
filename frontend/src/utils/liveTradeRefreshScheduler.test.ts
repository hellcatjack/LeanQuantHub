import { describe, expect, it } from "vitest";

import { buildSymbolListKey } from "./liveTradeRefreshScheduler";

describe("buildSymbolListKey", () => {
  it("builds stable key for same symbol contents", () => {
    const a = ["ALB", "gsat", "  TYL "];
    const b = ["alb", "GSAT", "TYL"];
    expect(buildSymbolListKey(a)).toBe(buildSymbolListKey(b));
  });

  it("ignores empty values", () => {
    expect(buildSymbolListKey(["ALB", "", " ", null as unknown as string, "GSAT"])).toBe(
      "ALB|GSAT"
    );
  });
});
