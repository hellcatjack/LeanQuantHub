import { describe, it, expect } from "vitest";

import { PIPELINE_BACKTEST_DEFAULTS } from "./ProjectsPage";

describe("pipeline backtest defaults", () => {
  it("includes cold_start_turnover", () => {
    expect(PIPELINE_BACKTEST_DEFAULTS.cold_start_turnover).toBe(0.3);
  });

  it("includes risk_off_lookback_days", () => {
    expect(PIPELINE_BACKTEST_DEFAULTS.risk_off_lookback_days).toBe(120);
  });

  it("defaults defensive basket to SGOV and VGSH", () => {
    expect(PIPELINE_BACKTEST_DEFAULTS.risk_off_symbols).toBe("SGOV,VGSH");
  });
});
