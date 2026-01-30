import { test, expect } from "@playwright/test";

const mockApi = async (page: any) => {
  await page.route("**/api/brokerage/status/overview", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        connection: {
          status: "connected",
          message: "ok",
          last_heartbeat: "2026-01-28T00:00:00Z",
          updated_at: "2026-01-28T00:00:00Z",
        },
        stream: {
          status: "connected",
          subscribed_count: 0,
          last_heartbeat: "2026-01-28T00:00:00Z",
          ib_error_count: 0,
          last_error: null,
          market_data_type: "delayed",
        },
        snapshot_cache: {
          status: "fresh",
          last_snapshot_at: "2026-01-28T00:00:00Z",
          symbol_sample_count: 0,
        },
        orders: {},
        alerts: {},
        partial: false,
        errors: [],
        refreshed_at: "2026-01-28T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/brokerage/settings", (route: any) =>
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
        created_at: "2026-01-28T00:00:00Z",
        updated_at: "2026-01-28T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/brokerage/state", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        status: "connected",
        message: "ok",
        last_heartbeat: "2026-01-28T00:00:00Z",
        updated_at: "2026-01-28T00:00:00Z",
      }),
    })
  );
  await page.route("**/api/brokerage/stream/status", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "connected",
        last_heartbeat: "2026-01-28T00:00:00Z",
        subscribed_symbols: [],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "delayed",
      }),
    })
  );
  await page.route("**/api/brokerage/history/jobs", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.route("**/api/brokerage/account/summary", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ name: "NetLiquidation", value: 1000 }],
        refreshed_at: "2026-01-28T00:00:00Z",
        stale: false,
      }),
    })
  );
  await page.route("**/api/brokerage/account/positions**", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        refreshed_at: "2026-01-28T00:00:00Z",
        stale: false,
      }),
    })
  );
  await page.route("**/api/trade/settings", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        risk_defaults: {},
        execution_data_source: "ib",
      }),
    })
  );
  await page.route("**/api/trade/runs**", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.route("**/api/trade/orders**", (route: any) =>
    route.fulfill({
      status: 200,
      headers: { "x-total-count": "0" },
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.route("**/api/trade/receipts**", (route: any) =>
    route.fulfill({
      status: 200,
      headers: { "x-total-count": "2" },
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            time: "2026-01-28T12:00:00Z",
            kind: "submit",
            order_id: 1,
            client_order_id: "manual-1",
            symbol: "AAPL",
            side: "BUY",
            quantity: 1,
            filled_quantity: 0,
            fill_price: null,
            exec_id: null,
            status: "SUBMITTED",
            source: "lean",
          },
          {
            time: "2026-01-28T12:00:02Z",
            kind: "fill",
            order_id: 1,
            client_order_id: "manual-1",
            symbol: "AAPL",
            side: "BUY",
            quantity: 1,
            filled_quantity: 1,
            fill_price: 100,
            exec_id: "EXEC-1",
            status: "FILLED",
            source: "db",
          },
        ],
        total: 2,
        warnings: [],
      }),
    })
  );
};

test("live trade monitor shows receipts tab", async ({ page }) => {
  await mockApi(page);
  await page.goto("/live-trade");
  const tab = page.getByRole("button", { name: /回执|Receipts/i });
  await tab.click();
  const table = page.getByTestId("trade-receipts-table");
  await expect(table).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(2);
  await expect(table).toContainText("AAPL");
  await expect(table).toContainText("manual-1");
  const monitorCard = page
    .locator(".card")
    .filter({ has: page.locator(".card-title", { hasText: /实盘监控|Monitor/i }) })
    .first();
  await expect(
    monitorCard.locator(".card-meta", {
      hasText: /最近订单与执行明细|Recent orders and execution details/i,
    })
  ).toBeVisible();
});
