import { test, expect } from "@playwright/test";

test("live trade page shows connection state", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(
    page.locator(".overview-label", { hasText: /连接状态|Connection status/i })
  ).toBeVisible();
});

test("live trade page shows bridge status card", async ({ page }) => {
  await page.route("**/api/brokerage/status/overview", (route) =>
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
  await page.route("**/api/brokerage/settings", (route) =>
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
  await page.route("**/api/brokerage/state", (route) =>
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
  await page.route("**/api/brokerage/stream/status", (route) =>
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
  await page.goto("/live-trade");
  await expect(
    page.locator(".overview-label", { hasText: /Lean Bridge/i })
  ).toBeVisible();
});

test("live trade run table shows decision snapshot column", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByText(/决策快照|Decision Snapshot/i)).toBeVisible();
});

test("live trade page shows ib stream card", async ({ page }) => {
  await page.goto("/live-trade");
  const streamTitle = page.locator(".card-title", { hasText: /行情订阅|Market Stream/i });
  const streamCard = streamTitle.first().locator("..");
  await expect(streamCard).toBeVisible();
  await expect(
    streamCard.locator(".overview-label", { hasText: /行情类型|Market data type/i })
  ).toBeVisible();
  await expect(
    streamCard.locator(".meta-row span", { hasText: /最后错误|Last error/i })
  ).toBeVisible();
});

test("live trade page shows live warning in live mode", async ({ page }) => {
  await page.route("**/api/brokerage/settings", (route) =>
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
  await page.route("**/api/brokerage/state", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        status: "connected",
        message: "ok",
        last_heartbeat: "2026-01-22T00:00:00Z",
        updated_at: "2026-01-22T00:00:00Z",
      }),
    })
  );
  await page.goto("/live-trade");
  await expect(
    page.locator(".form-error", { hasText: /实盘模式|Live mode/i })
  ).toBeVisible();
});

test("live trade positions table uses scroll wrapper", async ({ page }) => {
  await page.route("**/api/brokerage/account/positions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            symbol: "SPY",
            position: 12,
            avg_cost: 420.5,
            market_price: 432.1,
            market_value: 5185.2,
            unrealized_pnl: 139.2,
            realized_pnl: 0.0,
            account: "DU123456",
            currency: "USD",
          },
        ],
        refreshed_at: "2026-01-24T00:00:00Z",
        stale: false,
      }),
    })
  );
  await page.goto("/live-trade");
  const table = page.locator(".table-scroll").first();
  await expect(table).toBeVisible();
});

test("live trade shows stale positions hint when bridge stale and positions empty", async ({
  page,
}) => {
  await page.route("**/api/brokerage/settings", (route) =>
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
        created_at: "2026-01-25T00:00:00Z",
        updated_at: "2026-01-25T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/brokerage/status/overview", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        connection: {
          status: "connected",
          message: "ok",
          last_heartbeat: "2026-01-25T00:00:00Z",
          updated_at: "2026-01-25T00:00:00Z",
        },
        stream: {
          status: "connected",
          subscribed_count: 0,
          last_heartbeat: "2026-01-25T00:00:00Z",
          ib_error_count: 0,
          last_error: null,
          market_data_type: "delayed",
        },
        snapshot_cache: {
          status: "fresh",
          last_snapshot_at: "2026-01-25T00:00:00Z",
          symbol_sample_count: 0,
        },
        orders: {},
        alerts: {},
        partial: false,
        errors: [],
        refreshed_at: "2026-01-25T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/brokerage/state", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        status: "connected",
        message: "ok",
        last_heartbeat: "2026-01-25T00:00:00Z",
        updated_at: "2026-01-25T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/brokerage/stream/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "connected",
        last_heartbeat: "2026-01-25T00:00:00Z",
        subscribed_symbols: [],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "delayed",
      }),
    })
  );
  await page.route("**/api/brokerage/history/jobs", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.route("**/api/brokerage/account/summary**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: {},
        refreshed_at: "2026-01-25T00:00:00Z",
        source: "lean_bridge",
        stale: true,
        full: false,
      }),
    })
  );
  await page.route("**/api/brokerage/account/positions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        refreshed_at: "2026-01-25T00:00:00Z",
        stale: true,
      }),
    })
  );
  await page.route("**/api/trade/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.route("**/api/trade/orders**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );

  await page.goto("/live-trade");
  await expect(
    page.locator(".form-hint.warn", {
      hasText: /持仓为空且数据已过期|Positions are empty and data is stale/i,
    })
  ).toBeVisible();
});
