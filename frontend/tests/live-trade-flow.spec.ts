import { test, expect } from "@playwright/test";

const shouldRun = process.env.PLAYWRIGHT_LIVE_TRADE === "1";

test("paper flow - account summary testids", async ({ page }) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1 and live env");

  await page.goto("/live-trade");

  const netLiq = page.getByTestId("account-summary-NetLiquidation-value");
  await expect(netLiq).toBeVisible();
});
