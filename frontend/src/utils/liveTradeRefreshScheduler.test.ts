import { describe, expect, it } from "vitest";

import { REFRESH_INTERVALS } from "./liveTradeRefreshScheduler";

describe("liveTradeRefreshScheduler", () => {
  it("includes bridge in auto refresh intervals", () => {
    expect(Object.keys(REFRESH_INTERVALS)).toContain("bridge");
  });
});
