import { describe, expect, it } from "vitest";
import { getOverviewStatus } from "./ibOverview";

describe("getOverviewStatus", () => {
  it("returns partial when overview is partial", () => {
    expect(getOverviewStatus({ partial: true })).toBe("partial");
  });

  it("returns ok when connected", () => {
    expect(getOverviewStatus({ connection: { status: "connected" } })).toBe("ok");
  });

  it("returns down when disconnected", () => {
    expect(getOverviewStatus({ connection: { status: "disconnected" } })).toBe("down");
  });

  it("returns unknown when empty", () => {
    expect(getOverviewStatus(null)).toBe("unknown");
  });
});
