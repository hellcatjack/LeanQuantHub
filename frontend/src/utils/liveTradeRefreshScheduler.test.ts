import { describe, expect, it } from "vitest";
import {
  REFRESH_INTERVALS,
  buildSymbolListKey,
  hasActiveTradeOrderStatus,
  hasActiveTradeRunStatus,
  resolveRefreshIntervals,
} from "./liveTradeRefreshScheduler";

describe("liveTradeRefreshScheduler", () => {
  it("returns fast refresh intervals when execution is hot", () => {
    const resolved = resolveRefreshIntervals({ hotExecution: true });
    expect(resolved.monitor).toBe(3_000);
    expect(resolved.execution).toBe(5_000);
    expect(resolved.positions).toBe(5_000);
  });

  it("keeps default refresh intervals when execution is idle", () => {
    const resolved = resolveRefreshIntervals({ hotExecution: false });
    expect(resolved).toEqual(REFRESH_INTERVALS);
  });

  it("treats active order statuses as hot", () => {
    expect(hasActiveTradeOrderStatus("new")).toBe(true);
    expect(hasActiveTradeOrderStatus("SUBMITTED")).toBe(true);
    expect(hasActiveTradeOrderStatus("partial")).toBe(true);
    expect(hasActiveTradeOrderStatus("cancel_requested")).toBe(true);
  });

  it("treats terminal order statuses as not hot", () => {
    expect(hasActiveTradeOrderStatus("filled")).toBe(false);
    expect(hasActiveTradeOrderStatus("canceled")).toBe(false);
    expect(hasActiveTradeOrderStatus("rejected")).toBe(false);
    expect(hasActiveTradeOrderStatus("skipped")).toBe(false);
    expect(hasActiveTradeOrderStatus("")).toBe(false);
  });

  it("treats unknown non-empty order status as active for safety", () => {
    expect(hasActiveTradeOrderStatus("pending_submit")).toBe(true);
  });

  it("detects active and terminal run statuses", () => {
    expect(hasActiveTradeRunStatus("running")).toBe(true);
    expect(hasActiveTradeRunStatus("submitted")).toBe(true);
    expect(hasActiveTradeRunStatus("done")).toBe(false);
    expect(hasActiveTradeRunStatus("failed")).toBe(false);
    expect(hasActiveTradeRunStatus("partial")).toBe(false);
    expect(hasActiveTradeRunStatus("")).toBe(false);
  });

  it("builds stable key for same symbol contents", () => {
    const a = ["ALB", "gsat", "  TYL "];
    const b = ["alb", "GSAT", "TYL"];
    expect(buildSymbolListKey(a)).toBe(buildSymbolListKey(b));
  });

  it("ignores empty values in symbol list key", () => {
    expect(buildSymbolListKey(["ALB", "", " ", null as unknown as string, "GSAT"])).toBe(
      "ALB|GSAT"
    );
  });
});
