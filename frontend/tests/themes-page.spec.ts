import { test, expect } from "@playwright/test";

test("themes detail shows system base manual symbols", async ({ page }) => {
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
            id: 18,
            name: "初始模型项目",
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

    if (path === "/api/projects/18/config") {
      return json({
        project_id: 18,
        source: "version",
        updated_at: "2026-01-25T00:00:00Z",
        config: {
          themes: [
            {
              key: "AI_COLLECTION",
              label: "人工智能集合",
              weight: 0.1,
              manual: [],
              exclude: [],
              system_base: {
                label: "人工智能集合",
                manual: ["NVDA", "AMD"],
                exclude: [],
                keywords: [],
              },
              system: {
                theme_id: 99,
                version_id: 123,
                version: "v1",
                source: "config",
                mode: "follow_latest",
              },
            },
          ],
          categories: [{ key: "AI_COLLECTION", label: "人工智能集合" }],
          weights: { AI_COLLECTION: 0.1 },
        },
      });
    }

    if (path === "/api/projects/18/themes/summary") {
      return json({
        project_id: 18,
        updated_at: "2026-01-25T00:00:00Z",
        total_symbols: 2,
        themes: [
          {
            key: "AI_COLLECTION",
            label: "人工智能集合",
            symbols: 2,
            sample: ["NVDA", "AMD"],
            sample_types: { NVDA: "STOCK", AMD: "STOCK" },
            manual_symbols: ["NVDA", "AMD"],
            exclude_symbols: [],
          },
        ],
      });
    }

    if (path === "/api/projects/18/themes/symbols") {
      if (url.searchParams.get("category") === "AI_COLLECTION") {
        return json({
          project_id: 18,
          category: "AI_COLLECTION",
          label: "人工智能集合",
          symbols: ["NVDA", "AMD"],
          auto_symbols: [],
          manual_symbols: ["NVDA", "AMD"],
          exclude_symbols: [],
          symbol_types: { NVDA: "STOCK", AMD: "STOCK" },
        });
      }
    }

    if (path === "/api/system-themes") {
      return json({ items: [], total: 0, page: 1, page_size: 200 });
    }

    if (path === "/api/system-themes/projects/18/reports/page") {
      return json({ items: [], total: 0, page: 1, page_size: 5 });
    }

    return json({});
  });

  await page.goto("/themes");
  await page.selectOption(".themes-project-select select", "18");

  const row = page.locator("tr", {
    has: page.locator(".theme-key", { hasText: "AI_COLLECTION" }),
  });
  await expect(row).toBeVisible();
  await row.locator("button.link-button").click();

  await expect(page.locator(".theme-detail-panel")).toBeVisible();
  const manualSection = page.locator(".theme-detail-section").nth(1);
  await expect(manualSection.locator(".theme-chip")).toHaveCount(2);
});
