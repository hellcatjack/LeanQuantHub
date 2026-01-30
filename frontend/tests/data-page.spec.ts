import { test, expect } from "@playwright/test";

test("data page shows id chips for pretrade runs", async ({ page }) => {
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
      return json({
        items: [{ id: 18, name: "Project 18" }],
        total: 1,
        page: 1,
        page_size: 200,
      });
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
      return json([
        {
          id: 2001,
          project_id: 18,
          name: "Template A",
          is_active: true,
          params: null,
          steps: [],
        },
      ]);
    }
    if (path === "/api/pretrade/runs/page") {
      return json({
        items: [
          {
            id: 1001,
            project_id: 18,
            status: "finished",
            created_at: "2026-01-25T00:00:00Z",
            updated_at: "2026-01-25T00:00:00Z",
            window_start: null,
            window_end: null,
            deadline_at: null,
            fallback_used: false,
            fallback_run_id: null,
            message: "",
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      });
    }
    if (path.startsWith("/api/pretrade/runs/")) {
      return json({
        run: {
          id: 1001,
          project_id: 18,
          status: "finished",
          created_at: "2026-01-25T00:00:00Z",
          updated_at: "2026-01-25T00:00:00Z",
          window_start: null,
          window_end: null,
          deadline_at: null,
          fallback_used: false,
          fallback_run_id: null,
          message: "",
        },
        steps: [
          {
            id: 5001,
            run_id: 1001,
            step_key: "calendar_refresh",
            step_order: 0,
            status: "success",
            progress: 1,
            retry_count: 0,
            next_retry_at: null,
            message: "",
            log_path: null,
            params: null,
            artifacts: null,
            created_at: "2026-01-25T00:00:00Z",
            started_at: "2026-01-25T00:00:00Z",
            ended_at: "2026-01-25T00:00:01Z",
            updated_at: "2026-01-25T00:00:01Z",
          },
          {
            id: 5002,
            run_id: 1001,
            step_key: "decision_snapshot",
            step_order: 1,
            status: "success",
            progress: 1,
            retry_count: 0,
            next_retry_at: null,
            message: "",
            log_path: null,
            params: null,
            artifacts: null,
            created_at: "2026-01-25T00:00:01Z",
            started_at: "2026-01-25T00:00:01Z",
            ended_at: "2026-01-25T00:00:02Z",
            updated_at: "2026-01-25T00:00:02Z",
          },
          {
            id: 5003,
            run_id: 1001,
            step_key: "bridge_gate",
            step_order: 2,
            status: "success",
            progress: 1,
            retry_count: 0,
            next_retry_at: null,
            message: "",
            log_path: null,
            params: null,
            artifacts: {
              bridge_gate: {
                ok: true,
                missing: [],
                stale: [],
                checks: {
                  heartbeat: { ok: true, updated_at: "2026-01-25T00:00:02Z" },
                  account: { ok: true, updated_at: "2026-01-25T00:00:02Z" },
                  positions: { ok: true, updated_at: "2026-01-25T00:00:02Z" },
                  quotes: { ok: true, updated_at: "2026-01-25T00:00:02Z" },
                },
              },
            },
            created_at: "2026-01-25T00:00:02Z",
            started_at: "2026-01-25T00:00:02Z",
            ended_at: "2026-01-25T00:00:03Z",
            updated_at: "2026-01-25T00:00:03Z",
          },
        ],
      });
    }
    if (path === "/api/datasets/sync-jobs/speed") {
      return json({
        window_seconds: 60,
        completed: 0,
        rate_per_min: 0,
        running: 0,
        pending: 0,
        target_rpm: 0,
        effective_min_delay_seconds: 0,
      });
    }
    if (path === "/api/datasets/alpha-rate") {
      return json({
        max_rpm: 120,
        rpm_floor: 0,
        rpm_ceil: 0,
        rpm_step_down: 0,
        rpm_step_up: 0,
        min_delay_seconds: 0.1,
        effective_min_delay_seconds: 0.1,
        rate_limit_sleep: 10,
        rate_limit_retries: 3,
        max_retries: 3,
        auto_tune: false,
        min_delay_floor_seconds: 0,
        min_delay_ceil_seconds: 0,
        tune_step_seconds: 0,
        tune_window_seconds: 0,
        tune_target_ratio_low: 0,
        tune_target_ratio_high: 0,
        tune_cooldown_seconds: 0,
        source: "alpha",
        path: "",
      });
    }
    if (path === "/api/datasets/alpha-fetch-config") {
      return json({
        alpha_incremental_enabled: false,
        alpha_compact_days: 30,
        source: "alpha",
        path: "",
        updated_at: "2026-01-25T00:00:00Z",
      });
    }
    if (path === "/api/datasets/trading-calendar") {
      return json({
        source: "auto",
        exchange: "XNYS",
        start_date: "1990-01-01",
        end_date: "",
        refresh_days: 30,
        override_enabled: false,
        path: "",
        calendar_source: "",
        calendar_exchange: "",
        calendar_start: "",
        calendar_end: "",
        calendar_sessions: 0,
        overrides_applied: 0,
      });
    }
    if (path === "/api/datasets/trading-calendar/preview") {
      return json({
        month: "2026-01",
        as_of_date: "2026-01-25",
        recent_trading_days: [],
        upcoming_trading_days: [],
        week_days: [],
        month_days: [],
      });
    }
    if (path === "/api/datasets/bulk-auto-config") {
      return json({
        status: "all",
        batch_size: 200,
        only_missing: false,
        min_delay_seconds: 0.1,
        refresh_listing_mode: "stale_only",
        refresh_listing_ttl_days: 7,
        project_only: true,
        source: "alpha",
        path: "",
      });
    }
    if (path === "/api/datasets/alpha-gap-summary") {
      return json({
        latest_complete: "2026-01-25",
        total: 0,
        with_coverage: 0,
        missing_coverage: 0,
        up_to_date: 0,
        gap_0_30: 0,
        gap_31_120: 0,
        gap_120_plus: 0,
      });
    }
    if (path === "/api/universe/themes") {
      return json({ items: [] });
    }
    if (path.startsWith("/api/universe/themes/") && path.endsWith("/symbols")) {
      return json({ key: "", symbols: [] });
    }
    if (path === "/api/datasets/theme-coverage") {
      return json({
        theme_key: "",
        total_symbols: 0,
        covered_symbols: 0,
        missing_symbols: [],
      });
    }
    if (path === "/api/datasets/bulk-sync-jobs/latest") {
      return json({
        id: 0,
        dataset_id: 0,
        dataset_name: "",
        dataset_code: "",
        status: "idle",
        created_at: "2026-01-25T00:00:00Z",
      });
    }

    return json({});
  });

  await page.goto("/data");
  await expect(
    page.locator(".id-chip-text", { hasText: /Run#1001|批次#1001/i }).first()
  ).toBeVisible();
  await expect(
    page.locator(".pretrade-step-name", { hasText: /Lean Bridge 交易门禁|Lean bridge gate/i }).first()
  ).toBeVisible();
  await expect(
    page.locator(".progress-meta .pill", { hasText: /Data gate|数据门禁/i }).first()
  ).toBeVisible();
  await expect(
    page.locator(".progress-meta .pill", { hasText: /Trade gate|交易门禁/i }).first()
  ).toBeVisible();
});
