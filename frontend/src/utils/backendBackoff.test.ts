import { describe, expect, it } from "vitest";

import {
  BACKOFF_BASE_MS,
  BACKOFF_MAX_MS,
  computeBackendBackoffMs,
  isBackendBackoffEligibleError,
} from "./backendBackoff";

describe("computeBackendBackoffMs", () => {
  it("returns 0 for non-positive failures", () => {
    expect(computeBackendBackoffMs(0)).toBe(0);
    expect(computeBackendBackoffMs(-1)).toBe(0);
  });

  it("grows exponentially and caps at max", () => {
    expect(computeBackendBackoffMs(1)).toBe(BACKOFF_BASE_MS);
    expect(computeBackendBackoffMs(2)).toBe(BACKOFF_BASE_MS * 2);
    expect(computeBackendBackoffMs(10)).toBe(BACKOFF_MAX_MS);
  });
});

describe("isBackendBackoffEligibleError", () => {
  it("treats network/no-response errors as eligible", () => {
    expect(isBackendBackoffEligibleError({ hasResponse: false })).toBe(true);
  });

  it("treats 5xx/429/408 as eligible", () => {
    expect(isBackendBackoffEligibleError({ hasResponse: true, status: 500 })).toBe(true);
    expect(isBackendBackoffEligibleError({ hasResponse: true, status: 503 })).toBe(true);
    expect(isBackendBackoffEligibleError({ hasResponse: true, status: 429 })).toBe(true);
    expect(isBackendBackoffEligibleError({ hasResponse: true, status: 408 })).toBe(true);
  });

  it("treats common network timeout codes as eligible", () => {
    expect(
      isBackendBackoffEligibleError({ hasResponse: true, status: 400, code: "ECONNABORTED" })
    ).toBe(true);
    expect(
      isBackendBackoffEligibleError({ hasResponse: true, status: 400, code: "ERR_NETWORK" })
    ).toBe(true);
  });

  it("ignores non-eligible client errors", () => {
    expect(isBackendBackoffEligibleError({ hasResponse: true, status: 404 })).toBe(false);
    expect(isBackendBackoffEligibleError({ hasResponse: true, status: 400 })).toBe(false);
  });
});

