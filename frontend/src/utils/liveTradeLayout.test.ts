import { describe, it, expect } from "vitest";
import { getLiveTradeSections, LIVE_TRADE_REFRESH_MS } from "./liveTradeLayout";

describe("live trade layout", () => {
  it("defines main and advanced sections in order", () => {
    const sections = getLiveTradeSections();
    expect(sections.main).toEqual([
      "connection",
      "project",
      "account",
      "positions",
      "monitor",
    ]);
    expect(sections.advanced).toContain("config");
    expect(sections.advanced).toContain("marketHealth");
  });

  it("uses agreed refresh intervals", () => {
    expect(LIVE_TRADE_REFRESH_MS.connection).toBe(10000);
    expect(LIVE_TRADE_REFRESH_MS.monitor).toBe(15000);
    expect(LIVE_TRADE_REFRESH_MS.account).toBe(60000);
  });
});
