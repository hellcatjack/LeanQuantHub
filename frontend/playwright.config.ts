import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL || "http://192.168.1.31:8081";
const useLocalServer = baseURL === "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  use: {
    baseURL,
    headless: true,
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
