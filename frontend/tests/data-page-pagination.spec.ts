import { test, expect } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:4173";

test("data page shows pagination bars for PIT and PreTrade", async ({ page }) => {
  await page.goto(`${BASE_URL}/data`);
  await expect(page.getByText("PIT 周度任务")).toBeVisible();
  await expect(page.getByText("PIT 财报任务")).toBeVisible();
  await expect(page.getByText("PreTrade 周度检查")).toBeVisible();

  const paginations = page.locator(".pagination");
  const count = await paginations.count();
  expect(count).toBeGreaterThanOrEqual(3);
});
