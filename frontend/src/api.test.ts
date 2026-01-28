import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveApiBaseUrl } from "./api";

describe("resolveApiBaseUrl", () => {
  const originalWindow = globalThis.window;

  afterEach(() => {
    vi.unstubAllEnvs();
    globalThis.window = originalWindow;
  });

  it("uses env base when provided", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    expect(resolveApiBaseUrl()).toBe("https://api.example.com");
  });

  it("uses window origin when env is missing", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    globalThis.window = {
      location: {
        origin: "https://stocklean.example.com",
        protocol: "https:",
        hostname: "stocklean.example.com",
        host: "stocklean.example.com",
      },
    } as Window & typeof globalThis;

    expect(resolveApiBaseUrl()).toBe("https://stocklean.example.com");
  });

  it("falls back to localhost when no window available", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    // ensure window is undefined in this test
    globalThis.window = undefined as unknown as Window & typeof globalThis;
    expect(resolveApiBaseUrl()).toBe("http://localhost:8021");
  });
});
