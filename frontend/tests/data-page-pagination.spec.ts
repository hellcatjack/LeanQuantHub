import { test, expect } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:4173";

test("data page shows pagination bars for PIT and PreTrade", async ({ page }) => {
  await page.goto(`${BASE_URL}/data`);
  await expect(page.getByText(/Data Management|数据管理/)).toBeVisible();
  await expect(
    page.getByText(/PIT (Weekly Snapshots|Weekly Job|周度快照|周度任务)/)
  ).toBeVisible();
  await expect(
    page.getByText(/PIT (Fundamental Snapshots|Fundamental Job|基本面快照|基本面任务)/)
  ).toBeVisible();
  await expect(page.getByText(/PreTrade (Checklist|周度检查)/)).toBeVisible();
  await expect(
    page.getByText(/Data gate|数据门禁|No runs yet|暂无运行记录/)
  ).toBeVisible();

  const paginations = page.locator(".pagination");
  const count = await paginations.count();
  expect(count).toBeGreaterThanOrEqual(3);
});
