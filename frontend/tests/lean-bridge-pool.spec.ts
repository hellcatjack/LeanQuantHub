import { test, expect } from "@playwright/test";

test("bridge pool page shows leader", async ({ page }) => {
  await page.goto("/live-trade/bridge-pool");
  await expect(page.getByRole("cell", { name: "Leader" })).toBeVisible();
});
