import { test, expect } from "@playwright/test";

test("data page global excludes CRUD", async ({ page }) => {
  const excludes: Array<{ symbol: string; enabled: boolean; reason?: string }> = [
    { symbol: "WY", enabled: true, reason: "legacy" },
  ];

  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const corsHeaders = {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
      "access-control-allow-headers": "*",
    };
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: corsHeaders, body: "" });
    }
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: corsHeaders,
        body: JSON.stringify(body),
      });

    if (path === "/api/universe/excludes") {
      if (route.request().method() === "GET") {
        return json({ items: excludes });
      }
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as { symbol: string; reason?: string };
        excludes.push({ symbol: body.symbol, enabled: true, reason: body.reason });
        return json({ symbol: body.symbol, enabled: true, reason: body.reason || "" });
      }
    }
    if (path.startsWith("/api/universe/excludes/") && route.request().method() === "PATCH") {
      const symbol = path.split("/").pop() || "";
      const body = route.request().postDataJSON() as { enabled?: boolean };
      const target = excludes.find((item) => item.symbol === symbol);
      if (target && typeof body.enabled === "boolean") {
        target.enabled = body.enabled;
      }
      return json({ symbol, enabled: body.enabled ?? true, reason: target?.reason || "" });
    }

    if (path === "/api/datasets/page") {
      return json({ items: [], total: 0, page: 1, page_size: 200 });
    }
    if (path === "/api/datasets/sync-jobs/page") {
      return json({ items: [], total: 0, page: 1, page_size: 200 });
    }
    if (path === "/api/datasets/bulk-sync-jobs/page") {
      return json({ items: [], total: 0, page: 1, page_size: 200 });
    }
    if (path === "/api/pit/weekly-jobs/page") {
      return json({ items: [], total: 0, page: 1, page_size: 10 });
    }
    if (path === "/api/pit/fundamental-jobs/page") {
      return json({ items: [], total: 0, page: 1, page_size: 10 });
    }
    if (path === "/api/projects/page") {
      return json({ items: [{ id: 18, name: "Project 18" }], total: 1, page: 1, page_size: 200 });
    }
    if (path === "/api/pretrade/settings") {
      return json({
        project_id: 18,
        window_start: "",
        window_end: "",
        template_id: null,
        max_retries: 0,
        retry_base_delay_seconds: 0,
        retry_max_delay_seconds: 0,
        deadline_time: "",
        deadline_timezone: "",
        update_project_only: false,
        auto_decision_snapshot: false,
        telegram_bot_token: "",
        telegram_chat_id: "",
      });
    }
    if (path === "/api/pretrade/templates") {
      return json([]);
    }
    if (path === "/api/pretrade/runs/page") {
      return json({ items: [], total: 0, page: 1, page_size: 20 });
    }
    if (path === "/api/pretrade/runs/overview") {
      return json({ success: 0, failed: 0, running: 0, queued: 0, skipped: 0, blocked: 0 });
    }

    return route.fulfill({ status: 404, headers: corsHeaders, body: "" });
  });

  await page.goto("/data");
  await expect(page.getByText(/全局排除列表|Global Exclude List/)).toBeVisible();

  await page.fill("input[name='exclude-symbol']", "ZZZ");
  await page.click("button:has-text('添加'), button:has-text('Add')");
  await expect(page.getByText("ZZZ")).toBeVisible();

  await page.click("button:has-text('禁用'), button:has-text('Disable')");
  await expect(page.getByText("WY")).toBeVisible();
});
