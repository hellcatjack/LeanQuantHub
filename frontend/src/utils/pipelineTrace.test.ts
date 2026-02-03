import { describe, expect, it } from "vitest";
import { parsePretradeRunId } from "./pipelineTrace";

describe("parsePretradeRunId", () => {
  it("parses valid pretrade trace id", () => {
    expect(parsePretradeRunId("pretrade:123")).toBe(123);
  });

  it("returns null for invalid input", () => {
    expect(parsePretradeRunId("trade:1")).toBeNull();
    expect(parsePretradeRunId("pretrade:")).toBeNull();
    expect(parsePretradeRunId("pretrade:abc")).toBeNull();
    expect(parsePretradeRunId(null)).toBeNull();
  });
});
