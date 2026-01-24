import { test, expect } from "@playwright/test";

test("live trade shows Lean Bridge status", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.locator(".overview-label", { hasText: /Lean Bridge/i })).toBeVisible();
});
