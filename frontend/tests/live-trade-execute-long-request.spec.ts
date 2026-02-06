import { test, expect } from "@playwright/test";

test.setTimeout(120_000);

test("live trade execute tolerates >10s request (no false timeout)", async ({ page }) => {
  const now = new Date().toISOString();
  const projectId = 18;
  const runId = 123;
  const snapshotId = 68;

  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    const reqHeaders = req.headers();
    const origin = reqHeaders["origin"] || "*";
    const acrh = reqHeaders["access-control-request-headers"] || "content-type";

    const corsHeaders: Record<string, string> = {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
      "Access-Control-Allow-Headers": acrh,
      // App reads X-Total-Count for paging on some endpoints.
      "Access-Control-Expose-Headers": "X-Total-Count",
      Vary: "Origin",
    };

    if (method === "OPTIONS") {
      return route.fulfill({ status: 204, headers: corsHeaders, body: "" });
    }

    const json = async (
      body: unknown,
      init: { status?: number; headers?: Record<string, string> } = {}
    ) => {
      await route.fulfill({
        status: init.status ?? 200,
        headers: { ...corsHeaders, ...(init.headers || {}) },
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    };

    if (path === "/api/projects/page") {
      return json({
        items: [{ id: projectId, name: "Project 18", description: "" }],
        total: 1,
        page: 1,
        page_size: 200,
      });
    }

    if (path === "/api/decisions/latest") {
      return json({
        id: snapshotId,
        project_id: projectId,
        status: "success",
        snapshot_date: "2026-02-06",
        summary: { selected_count: 36 },
      });
    }

    if (path === "/api/trade/settings") {
      return json({
        id: 1,
        risk_defaults: {},
        execution_data_source: "lean",
        created_at: now,
        updated_at: now,
      });
    }

    if (path === "/api/trade/runs" && method === "POST") {
      return json({
        id: runId,
        project_id: projectId,
        decision_snapshot_id: snapshotId,
        mode: "paper",
        status: "queued",
        params: { project_id: projectId, decision_snapshot_id: snapshotId, mode: "paper" },
        message: null,
        created_at: now,
        started_at: null,
        ended_at: null,
        updated_at: now,
        last_progress_at: null,
        progress_stage: null,
        progress_reason: null,
        stalled_at: null,
        stalled_reason: null,
      });
    }

    if (path === "/api/trade/runs" && method === "GET") {
      return json([
        {
          id: runId,
          project_id: projectId,
          decision_snapshot_id: snapshotId,
          mode: "paper",
          status: "queued",
          params: { project_id: projectId, decision_snapshot_id: snapshotId, mode: "paper" },
          message: null,
          created_at: now,
          started_at: null,
          ended_at: null,
          updated_at: now,
          last_progress_at: null,
          progress_stage: null,
          progress_reason: null,
          stalled_at: null,
          stalled_reason: null,
        },
      ]);
    }

    if (path === "/api/trade/orders") {
      return json([], { headers: { "X-Total-Count": "0" } });
    }

    if (path === "/api/trade/receipts") {
      return json(
        {
          items: [],
          total: 0,
          warnings: [],
        },
        { headers: { "X-Total-Count": "0" } }
      );
    }

    if (path === "/api/trade/guard") {
      return json({
        id: 1,
        project_id: projectId,
        trade_date: "2026-02-06",
        mode: "paper",
        status: "active",
        halt_reason: null,
        risk_triggers: 0,
        order_failures: 0,
        market_data_errors: 0,
        day_start_equity: 30000,
        equity_peak: 30000,
        last_equity: 30000,
        last_valuation_ts: now,
        valuation_source: "mock",
        cooldown_until: null,
        created_at: now,
        updated_at: now,
      });
    }

    if (path === `/api/trade/runs/${runId}/execute`) {
      // Simulate a long server-side execution (>10s) to ensure frontend does not time out.
      await new Promise((resolve) => setTimeout(resolve, 11_500));
      try {
        return await json({
          run_id: runId,
          status: "running",
          filled: 0,
          cancelled: 0,
          rejected: 0,
          skipped: 0,
          message: null,
          dry_run: false,
        });
      } catch {
        // If the client times out / aborts, Playwright may not allow fulfilling anymore.
        return;
      }
    }

    if (path === "/api/brokerage/settings") {
      return json({
        host: "127.0.0.1",
        port: 7497,
        client_id: 1,
        account_id: "",
        mode: "paper",
        market_data_type: "realtime",
        api_mode: "ib",
        use_regulatory_snapshot: false,
        updated_at: now,
      });
    }

    if (path === "/api/brokerage/state") {
      return json({
        status: "connected",
        message: null,
        updated_at: now,
      });
    }

    if (path === "/api/brokerage/stream/status") {
      return json({
        status: "connected",
        last_heartbeat: now,
        subscribed_symbols: [],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "realtime",
      });
    }

    if (path === "/api/brokerage/bridge/status") {
      return json({
        status: "ok",
        stale: false,
        last_heartbeat: now,
        updated_at: now,
        last_refresh_at: now,
        last_refresh_result: "success",
        last_refresh_reason: "auto",
        last_refresh_message: null,
        last_error: null,
      });
    }

    if (path === "/api/brokerage/bridge/refresh") {
      return json({ bridge_status: { status: "ok", stale: false, updated_at: now } });
    }

    if (path === "/api/brokerage/account/summary") {
      return json({
        items: { NetLiquidation: 30000, BuyingPower: 30000 },
        refreshed_at: now,
        source: "mock",
        stale: false,
        full: Boolean(url.searchParams.get("full") === "true"),
      });
    }

    if (path === "/api/brokerage/account/positions") {
      return json({
        items: [],
        refreshed_at: now,
        stale: false,
      });
    }

    if (path === "/api/brokerage/history-jobs") {
      return json([]);
    }

    if (path === "/api/brokerage/market/health") {
      return json({
        status: "ok",
        total: 0,
        success: 0,
        missing_symbols: [],
        errors: [],
      });
    }

    if (path === "/api/brokerage/contracts/refresh") {
      return json({
        total: 0,
        updated: 0,
        skipped: 0,
        errors: [],
        duration_sec: 0.01,
      });
    }

    // Default: keep page resilient even if it refreshes extra cards.
    return json({});
  });

  await page.goto("/live-trade");
  const projectSelect = page.getByTestId("live-trade-project-select");
  await expect(projectSelect.locator('option[value="18"]')).toHaveCount(1);
  await projectSelect.selectOption(String(projectId));

  await page.locator("details.algo-advanced > summary").click();

  await page.getByTestId("paper-trade-create").click();
  const runIdInput = page.getByTestId("paper-trade-run-id");
  await expect(runIdInput).toHaveValue(String(runId));

  await page.getByTestId("paper-trade-execute").click();
  const outcome = await Promise.race([
    page
      .getByTestId("paper-trade-result")
      .waitFor({ state: "visible", timeout: 70_000 })
      .then(() => "result"),
    page
      .getByTestId("paper-trade-error")
      .waitFor({ state: "visible", timeout: 70_000 })
      .then(() => "error"),
  ]);
  expect(outcome).toBe("result");
  await expect(page.getByTestId("paper-trade-error")).toHaveCount(0);
});
