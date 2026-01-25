import { test, expect } from "@playwright/test";

test("projects page shows project id chip", async ({ page }) => {
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    if (path === "/api/projects/page") {
      return json({
        items: [
          {
            id: 16,
            name: "Project 16",
            description: "",
            is_archived: false,
            created_at: "2026-01-25T00:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        page_size: 200,
      });
    }
    if (path === "/api/projects/16/versions/page") {
      return json({ items: [], total: 0, page: 1, page_size: 20 });
    }
    if (path === "/api/projects/16/versions") {
      return json([]);
    }
    if (path === "/api/system-themes") {
      return json({ items: [], total: 0, page: 1, page_size: 200 });
    }
    if (path === "/api/algorithms") {
      return json([]);
    }
    if (path === "/api/ml/train-jobs") {
      return json([]);
    }
    if (path === "/api/factor-scores/jobs") {
      return json([]);
    }
    if (path === "/api/ml/pipelines") {
      return json([]);
    }
    if (path === "/api/projects/16/backtests") {
      return json([]);
    }
    if (path === "/api/projects/16/data-status") {
      return json({
        project_id: 16,
        data_root: "/data/share/stock/data",
        membership: { records: 0, symbols: 0 },
        universe: { records: 0, sp500_count: 0, theme_count: 0 },
        themes: { records: 0, categories: [] },
        metrics: { records: 0 },
        prices: { stooq_files: 0, yahoo_files: 0 },
        backtest: { updated_at: null, summary: null },
      });
    }
    if (path === "/api/projects/16/config") {
      return json({
        project_id: 16,
        config: {},
        source: "default",
        updated_at: "2026-01-25T00:00:00Z",
      });
    }
    if (path === "/api/projects/16/themes/summary") {
      return json({
        project_id: 16,
        themes: [],
        updated_at: "2026-01-25T00:00:00Z",
      });
    }
    if (path === "/api/automation/weekly-jobs/latest") {
      return json({
        id: 1,
        status: "idle",
        created_at: "2026-01-25T00:00:00Z",
      });
    }

    return json({});
  });

  await page.goto("/projects");
  await expect(
    page.locator(".project-item-title", { hasText: "Project 16" })
  ).toBeVisible();
  const chip = page.locator(".project-item-meta .id-chip-text");
  await expect(chip).toBeVisible();
  await expect(chip).toContainText(/#16/i);
});
