import { test, expect } from "@playwright/test";

test("live trade page shows connection state", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(
    page.locator(".meta-row span", { hasText: /连接状态|Connection status/i })
  ).toBeVisible();
});

test("live trade run table shows decision snapshot column", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByText(/决策快照|Decision Snapshot/i)).toBeVisible();
});
