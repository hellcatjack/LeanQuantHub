import { describe, expect, it } from "vitest";
import {
  formatBridgeRefreshReason,
  formatBridgeRefreshResult,
  getBridgeRefreshHint,
} from "./bridgeRefreshHint";

describe("bridge refresh hint helpers", () => {
  const t = (key: string, params?: Record<string, string>) => {
    if (key === "trade.refreshHint.generic") {
      return `GEN:${params?.result}|${params?.reason}`;
    }
    return key;
  };

  it("formats refresh result and reason with fallback", () => {
    expect(formatBridgeRefreshResult(t, "skipped")).toBe("skipped");
    expect(formatBridgeRefreshReason(t, "rate_limited")).toBe("rate_limited");
    expect(formatBridgeRefreshResult(t, null)).toBe("common.none");
  });

  it("builds generic refresh hint with details", () => {
    expect(getBridgeRefreshHint(t, "skipped", "manual")).toBe("GEN:skipped|manual");
  });
});
