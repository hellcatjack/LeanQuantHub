import { describe, expect, it } from "vitest";

import { getLiveTradeSections } from "./liveTradeLayout";

describe("liveTradeLayout", () => {
  it("defines main row sections for live trade", () => {
    const sections = getLiveTradeSections();
    expect(sections.mainRow).toEqual(["connection", "account", "positions"]);
  });

  it("keeps monitor, execution and risk overview visible by default", () => {
    const sections = getLiveTradeSections();
    expect(sections.main).toEqual(["monitor", "guard", "execution", "symbolSummary"]);
    expect(sections.advanced).toEqual(["config", "marketHealth", "contracts", "history"]);
  });
});
