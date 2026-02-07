import { test, expect } from "@playwright/test";

test.setTimeout(120_000);

test("extended-hours manual orders use LMT and default to latest quote", async ({ page }) => {
  const now = new Date().toISOString();
  const projectId = 18;
  const runId = 123;
  const snapshotId = 68;
  const symbol = "SPY";
  const marketPrice = 405.12;

  const seen: any[] = [];

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

    if (path === `/api/trade/runs/${runId}/detail`) {
      return json({
        run: {
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
        orders: [],
        fills: [],
        last_update_at: now,
      });
    }

    if (path === `/api/trade/runs/${runId}/symbols`) {
      return json({ items: [], last_update_at: now });
    }

    if (path === "/api/trade/orders" && method === "GET") {
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
        subscribed_symbols: [symbol],
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

    if (path === "/api/brokerage/stream/snapshot") {
      return json({
        symbol,
        data: { symbol, last: marketPrice, bid: marketPrice - 0.01, ask: marketPrice + 0.01, timestamp: now },
        error: null,
      });
    }

    if (path === "/api/brokerage/account/summary") {
      return json({
        items: { NetLiquidation: 30000 },
        refreshed_at: now,
        source: "lean_bridge",
        stale: false,
        full: false,
      });
    }

    if (path === "/api/brokerage/account/positions") {
      return json({
        items: [
          {
            symbol,
            position: 10,
            avg_cost: 400,
            market_price: marketPrice,
            market_value: marketPrice * 10,
            unrealized_pnl: (marketPrice - 400) * 10,
            realized_pnl: 0,
            account: "DU123",
            currency: "USD",
          },
        ],
        refreshed_at: now,
        stale: false,
      });
    }

    if (path === "/api/brokerage/history-jobs") {
      return json([]);
    }

    if (path === "/api/trade/orders/direct" && method === "POST") {
      const body = req.postDataJSON();
      seen.push(body);
      return json({
        order_id: 1,
        status: "NEW",
        execution_status: "submitted_lean",
        intent_path: "/tmp/intent.json",
        config_path: "/tmp/config.json",
        bridge_status: null,
        refresh_result: "success",
      });
    }

    return json({ detail: `unhandled:${method}:${path}` }, { status: 404 });
  });

  page.on("dialog", async (dialog) => {
    await dialog.accept();
  });

  await page.goto("/live-trade");
  const rows = page.getByTestId("account-positions-table").locator("tbody tr");
  await expect(rows).toHaveCount(1, { timeout: 60_000 });
  const row = rows.first();

  await row.locator("input.positions-action-input").fill("1");
  await row.getByTestId("positions-action-session").selectOption("pre");

  const limitInput = row.getByTestId("positions-action-limit-price");
  await expect(limitInput).toBeVisible();
  await expect(limitInput).not.toHaveValue("");

  await row.getByRole("button", { name: /买入|Buy/i }).click();
  await expect.poll(() => seen.length).toBe(1);

  expect(seen[0]).toMatchObject({
    symbol,
    side: "BUY",
    quantity: 1,
    order_type: "LMT",
    params: {
      source: "manual",
      session: "pre",
      allow_outside_rth: true,
    },
  });
  expect(seen[0].limit_price).toBeCloseTo(marketPrice, 4);
});

