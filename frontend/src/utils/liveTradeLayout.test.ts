import { describe, expect, it } from "vitest";

import { getLiveTradeSections } from "./liveTradeLayout";

describe("liveTradeLayout", () => {
  it("defines main row sections for live trade", () => {
    const sections = getLiveTradeSections();
    expect(sections.mainRow).toEqual(["connection", "account", "positions"]);
  });
});
