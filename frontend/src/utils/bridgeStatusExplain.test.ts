import { describe, expect, it } from "vitest";

import { getBridgeRefreshHintKey, getHeartbeatAgeSeconds, resolveConnectionReasonKey } from "./bridgeStatusExplain";

describe("bridgeStatusExplain", () => {
  it("returns rate limited hint key", () => {
    expect(getBridgeRefreshHintKey("skipped", "rate_limited")).toBe(
      "trade.refreshHint.rateLimited"
    );
  });

  it("returns heartbeat age seconds", () => {
    const now = new Date("2026-01-31T00:00:10Z");
    const ts = "2026-01-31T00:00:00Z";
    expect(getHeartbeatAgeSeconds(ts, now)).toBe(10);
  });

  it("maps lean bridge stale message", () => {
    expect(resolveConnectionReasonKey("lean bridge stale")).toBe(
      "trade.statusReason.bridgeStale"
    );
  });

  it("ignores lean bridge ok message", () => {
    expect(resolveConnectionReasonKey("lean bridge ok")).toBe(null);
  });
});
