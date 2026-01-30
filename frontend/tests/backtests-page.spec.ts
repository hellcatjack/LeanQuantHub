import { test, expect } from "@playwright/test";

test("backtests page shows id chips for run and project", async ({ page }) => {
  await page.route("**/api/backtests/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: 101,
            project_id: 18,
            status: "success",
            created_at: "2026-01-25T00:00:00Z",
            ended_at: "2026-01-25T00:10:00Z",
            metrics: {},
            report_id: 501,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    })
  );

  await page.goto("/backtests");
  await expect(
    page.locator(".id-chip-text", { hasText: /ID#101/i })
  ).toBeVisible();
  await expect(
    page.locator(".id-chip-text", { hasText: /项目#18|Project#18/i })
  ).toBeVisible();
});
