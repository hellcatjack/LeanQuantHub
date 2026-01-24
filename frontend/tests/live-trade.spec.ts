import { test, expect } from "@playwright/test";

test("live trade page shows connection state", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(
    page.locator(".meta-row span", { hasText: /连接状态|Connection status/i })
  ).toBeVisible();
});

test("live trade page shows bridge status card", async ({ page }) => {
  await page.route("**/api/ib/status/overview", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        connection: {
          status: "connected",
          message: "ok",
          last_heartbeat: "2026-01-24T00:00:00Z",
          updated_at: "2026-01-24T00:00:00Z",
        },
        stream: {
          status: "connected",
          subscribed_count: 1,
          last_heartbeat: "2026-01-24T00:00:00Z",
          ib_error_count: 0,
          last_error: null,
          market_data_type: "delayed",
        },
        snapshot_cache: {
          status: "fresh",
          last_snapshot_at: "2026-01-24T00:00:00Z",
          symbol_sample_count: 1,
        },
        orders: {},
        alerts: {},
        partial: false,
        errors: [],
        refreshed_at: "2026-01-24T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/ib/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        host: "127.0.0.1",
        port: 7497,
        client_id: 1,
        account_id: "DU123456",
        mode: "paper",
        market_data_type: "delayed",
        api_mode: "ib",
        use_regulatory_snapshot: false,
        created_at: "2026-01-24T00:00:00Z",
        updated_at: "2026-01-24T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/ib/state", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        status: "connected",
        message: "ok",
        last_heartbeat: "2026-01-24T00:00:00Z",
        updated_at: "2026-01-24T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/ib/stream/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "connected",
        last_heartbeat: "2026-01-24T00:00:00Z",
        subscribed_symbols: ["SPY"],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "delayed",
      }),
    })
  );
  await page.route("**/api/ib/account/summary**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: { NetLiquidation: 10000 },
        refreshed_at: "2026-01-24T00:00:00Z",
        source: "lean_bridge",
        stale: false,
        full: false,
      }),
    })
  );
  await page.route("**/api/ib/account/positions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], refreshed_at: null, stale: false }),
    })
  );
  await page.route("**/api/ib/history-jobs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/trade/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        risk_defaults: {},
        execution_data_source: "lean",
        created_at: "2026-01-24T00:00:00Z",
        updated_at: "2026-01-24T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/trade/orders**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );

  await page.goto("/live-trade");
  const bridgeCard = page.locator(".overview-card", {
    has: page.getByText(/Bridge 数据源|Bridge Data/i),
  });
  await expect(bridgeCard).toBeVisible();
  await expect(bridgeCard.getByText(/lean_bridge/i)).toBeVisible();
});

test("live trade run table shows decision snapshot column", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByText(/决策快照|Decision Snapshot/i)).toBeVisible();
});

test("live trade page shows ib stream card", async ({ page }) => {
  await page.goto("/live-trade");
  const streamCard = page.locator(".card", {
    has: page.getByText(/IB 行情订阅|IB Stream/i),
  });
  await expect(streamCard).toBeVisible();
  await expect(
    streamCard.locator(".overview-label", { hasText: /行情类型|Market data type/i })
  ).toBeVisible();
  await expect(
    streamCard.locator(".meta-row span", { hasText: /最后错误|Last error/i })
  ).toBeVisible();
});

test("live trade page shows live warning in live mode", async ({ page }) => {
  await page.route("**/api/ib/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        host: "127.0.0.1",
        port: 7497,
        client_id: 1,
        account_id: "DU123456",
        mode: "live",
        market_data_type: "delayed",
        api_mode: "ib",
        use_regulatory_snapshot: false,
        created_at: "2026-01-22T00:00:00Z",
        updated_at: "2026-01-22T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/ib/state", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        status: "connected",
        message: "ibapi ok",
        last_heartbeat: "2026-01-22T00:00:00Z",
        updated_at: "2026-01-22T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/ib/stream/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "connected",
        last_heartbeat: "2026-01-22T00:00:00Z",
        subscribed_symbols: ["SPY"],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "delayed",
      }),
    })
  );
  await page.route("**/api/ib/history-jobs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/trade/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        risk_defaults: {},
        execution_data_source: "ib",
        created_at: "2026-01-22T00:00:00Z",
        updated_at: "2026-01-22T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/trade/orders**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );

  await page.goto("/live-trade");
  await expect(
    page.locator(".form-error", { hasText: /实盘模式|Live mode/i })
  ).toBeVisible();
});

test("live trade positions table uses scroll wrapper", async ({ page }) => {
  await page.route("**/api/ib/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        host: "127.0.0.1",
        port: 7497,
        client_id: 1,
        account_id: "DU123456",
        mode: "paper",
        market_data_type: "delayed",
        api_mode: "ib",
        use_regulatory_snapshot: false,
        created_at: "2026-01-24T00:00:00Z",
        updated_at: "2026-01-24T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/ib/status/overview", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "connected",
        ib_state: { status: "connected", message: "ok" },
        ib_stream: { status: "connected", market_data_type: "delayed" },
        ib_settings: { mode: "paper", host: "127.0.0.1", port: 7497, client_id: 1 },
      }),
    })
  );
  await page.route("**/api/ib/state", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        status: "connected",
        message: "ibapi ok",
        last_heartbeat: "2026-01-24T00:00:00Z",
        updated_at: "2026-01-24T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/ib/stream/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "connected",
        last_heartbeat: "2026-01-24T00:00:00Z",
        subscribed_symbols: ["AAPL"],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "delayed",
      }),
    })
  );
  await page.route("**/api/ib/history-jobs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/ib/account/summary**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: {
          NetLiquidation: 10000,
          AvailableFunds: 5000,
        },
        refreshed_at: "2026-01-24T00:00:00Z",
        source: "refresh",
        stale: false,
        full: false,
      }),
    })
  );
  await page.route("**/api/ib/account/positions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            symbol: "AAPL",
            position: 10,
            avg_cost: 100,
            market_price: 105,
            market_value: 1050,
            unrealized_pnl: 50,
            realized_pnl: 0,
            account: "DU123456",
            currency: "USD",
          },
        ],
        refreshed_at: "2026-01-24T00:00:00Z",
        stale: false,
      }),
    })
  );
  await page.route("**/api/trade/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        risk_defaults: {},
        execution_data_source: "ib",
        created_at: "2026-01-24T00:00:00Z",
        updated_at: "2026-01-24T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/trade/orders**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );

  await page.goto("/live-trade");
  const positionsCard = page.locator(".card", {
    has: page.getByText(/当前持仓|Positions/i),
  });
  await expect(positionsCard).toBeVisible();
  const scrollWrapper = positionsCard.locator(".table-scroll");
  await expect(scrollWrapper).toBeVisible();
  await expect(scrollWrapper.locator("table")).toBeVisible();
});
