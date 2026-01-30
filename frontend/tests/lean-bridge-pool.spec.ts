import { test, expect } from "@playwright/test";

test("bridge pool page shows leader", async ({ page }) => {
  await page.goto("/live-trade/bridge-pool");
  await expect(page.getByText(/Leader/i)).toBeVisible();
});
