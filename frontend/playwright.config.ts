import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL || "http://192.168.1.31:8081";
const useLocalServer = baseURL === "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  // These e2e tests hit a shared backend + IB/TWS state, so high parallelism causes flakiness
  // (runs/orders interfere with each other). Default to 1 worker; override via E2E_WORKERS.
  workers: Math.max(1, Number.parseInt(process.env.E2E_WORKERS || "1", 10) || 1),
  use: {
    baseURL,
    headless: true,
    // Keep screenshots/layout assertions stable and match the target "headless desktop" resolution.
    viewport: { width: 2560, height: 1440 },
  },
  webServer: useLocalServer
    ? {
        command: "npm run dev -- --host 127.0.0.1 --port 4173",
        url: "http://127.0.0.1:4173",
        reuseExistingServer: true,
        timeout: 120_000,
      }
    : undefined,
});
