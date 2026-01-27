import { describe, it, expect } from "vitest";
import { buildOrderTag } from "./orderTag";

describe("buildOrderTag", () => {
  it("generates unique tag with trade_run_id and index", () => {
    const tag1 = buildOrderTag(25, 0, 1700000000000, 1234);
    const tag2 = buildOrderTag(25, 1, 1700000000000, 1234);
    expect(tag1).toContain("oi_25_0_");
    expect(tag2).toContain("oi_25_1_");
    expect(tag1).not.toBe(tag2);
  });
});
