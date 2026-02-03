import { describe, it, expect } from "vitest";

import { PIPELINE_BACKTEST_DEFAULTS } from "./ProjectsPage";

describe("pipeline backtest defaults", () => {
  it("includes cold_start_turnover", () => {
    expect(PIPELINE_BACKTEST_DEFAULTS.cold_start_turnover).toBe(0.3);
  });
});
