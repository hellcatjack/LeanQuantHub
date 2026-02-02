import { describe, expect, it } from "vitest";
import { findActivePretradeRun, isPretradeRunActive } from "./pretradeRunState";

describe("pretradeRunState", () => {
  it("detects active statuses", () => {
    expect(isPretradeRunActive("queued")).toBe(true);
    expect(isPretradeRunActive("running")).toBe(true);
    expect(isPretradeRunActive("failed")).toBe(false);
    expect(isPretradeRunActive("success")).toBe(false);
    expect(isPretradeRunActive("")).toBe(false);
    expect(isPretradeRunActive(null)).toBe(false);
  });

  it("finds first active run in list order", () => {
    const runs = [
      { id: 10, status: "failed" },
      { id: 11, status: "queued" },
      { id: 12, status: "running" },
    ];
    expect(findActivePretradeRun(runs)?.id).toBe(11);
  });

  it("returns undefined when no active run", () => {
    const runs = [
      { id: 20, status: "failed" },
      { id: 21, status: "success" },
    ];
    expect(findActivePretradeRun(runs)).toBeUndefined();
  });
});
