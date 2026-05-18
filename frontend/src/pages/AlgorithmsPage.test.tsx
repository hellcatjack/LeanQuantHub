import { describe, expect, it } from "vitest";

import { DEFAULT_ALGORITHM_PARAMS } from "./AlgorithmsPage";

describe("algorithm page defaults", () => {
  it("defaults defensive symbols to SGOV and VGSH", () => {
    expect(DEFAULT_ALGORITHM_PARAMS.defensive.symbols).toEqual(["SGOV", "VGSH"]);
  });
});
