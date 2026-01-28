import { test, expect } from "@playwright/test";

const now = "2026-01-24T00:00:00Z";

const fulfillJson = (route, body, headers = {}) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    headers,
    body: JSON.stringify(body),
  });

test("positions table buy/sell submits direct orders", async ({ page }) => {
  const orders: any[] = [];

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path === "/api/brokerage/settings") {
      return fulfillJson(route, {
        id: 1,
        host: "127.0.0.1",
        port: 7497,
        client_id: 101,
        account_id: "DU123456",
        mode: "paper",
        market_data_type: "delayed",
        api_mode: "ib",
        use_regulatory_snapshot: false,
        created_at: now,
        updated_at: now,
      });
    }

    if (path === "/api/brokerage/status/overview") {
      return fulfillJson(route, {
        connection: {
          status: "connected",
          message: "ok",
          last_heartbeat: now,
          updated_at: now,
        },
        stream: {
          status: "connected",
          subscribed_count: 1,
          last_heartbeat: now,
          ib_error_count: 0,
          last_error: null,
          market_data_type: "delayed",
        },
        snapshot_cache: {
          status: "fresh",
          last_snapshot_at: now,
          symbol_sample_count: 1,
        },
        orders: {},
        alerts: {},
        partial: false,
        errors: [],
        refreshed_at: now,
      });
    }

    if (path === "/api/brokerage/state") {
      return fulfillJson(route, {
        id: 1,
        status: "connected",
        message: "ok",
        last_heartbeat: now,
        updated_at: now,
      });
    }

    if (path === "/api/brokerage/stream/status") {
      return fulfillJson(route, {
        status: "connected",
        last_heartbeat: now,
        subscribed_symbols: ["SPY"],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "delayed",
      });
    }

    if (path === "/api/brokerage/stream/snapshot") {
      return fulfillJson(route, {
        symbol: "SPY",
        data: { last: 1, close: 1, timestamp: now },
        error: null,
      });
    }

    if (path === "/api/brokerage/history-jobs") {
      return fulfillJson(route, []);
    }

    if (path === "/api/brokerage/account/summary") {
      return fulfillJson(route, {
        items: { NetLiquidation: 30000 },
        refreshed_at: now,
        stale: false,
        full: false,
      });
    }

    if (path === "/api/brokerage/account/positions") {
      return fulfillJson(route, {
        items: [
          {
            symbol: "AAPL",
            position: 1,
            avg_cost: 180.5,
            market_price: 181.2,
            market_value: 181.2,
            unrealized_pnl: 0.7,
            realized_pnl: 0.0,
            account: "DU123456",
            currency: "USD",
          },
        ],
        refreshed_at: now,
        stale: false,
      });
    }

    if (path === "/api/projects/page") {
      return fulfillJson(route, {
        items: [{ id: 1, name: "Demo Project" }],
        total: 1,
        page: 1,
        page_size: 200,
      });
    }

    if (path === "/api/decisions/latest") {
      return route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "snapshot_not_found" }),
      });
    }

    if (path === "/api/trade/settings") {
      return fulfillJson(route, {
        id: 1,
        risk_defaults: null,
        execution_data_source: null,
        created_at: now,
        updated_at: now,
      });
    }

    if (path === "/api/trade/runs") {
      return fulfillJson(route, []);
    }

    if (path === "/api/trade/orders") {
      return fulfillJson(route, [], { "x-total-count": "0" });
    }

    if (path === "/api/trade/orders/direct") {
      orders.push(route.request().postDataJSON());
      return fulfillJson(route, {
        order_id: 1,
        status: "NEW",
        execution_status: "submitted_lean",
        intent_path: "/tmp/intent.json",
        config_path: "/tmp/config.json",
      });
    }

    return fulfillJson(route, {});
  });

  const dialogMessages: string[] = [];
  page.on("dialog", async (dialog) => {
    dialogMessages.push(dialog.message());
    await dialog.accept();
  });

  await page.goto("/live-trade");
  await page.getByTestId("account-positions-card").scrollIntoViewIfNeeded();

  const row = page.getByTestId("account-positions-table").locator("tbody tr").first();
  await row.getByRole("button", { name: /买入|Buy/i }).click();
  await expect.poll(() => orders.length).toBe(1);

  await row.getByRole("button", { name: /卖出|Sell/i }).click();
  await expect.poll(() => orders.length).toBe(2);

  expect(dialogMessages[0]).toMatch(/BUY|买入|Buy/);
  expect(dialogMessages[1]).toMatch(/SELL|卖出|Sell/);

  expect(orders[0]).toMatchObject({
    symbol: "AAPL",
    side: "BUY",
    quantity: 1,
    order_type: "MKT",
    project_id: 1,
    mode: "paper",
  });
  expect(orders[0].client_order_id).toMatch(/^oi_/);
  expect(orders[0].params).toMatchObject({ account: "DU123456", currency: "USD" });

  expect(orders[1]).toMatchObject({
    symbol: "AAPL",
    side: "SELL",
    quantity: 1,
    order_type: "MKT",
    project_id: 1,
    mode: "paper",
  });
  expect(orders[1].client_order_id).toMatch(/^oi_/);
  expect(orders[1].params).toMatchObject({ account: "DU123456", currency: "USD" });
});
