import { test, expect } from "@playwright/test";

const mockApi = async (page: any) => {
  await page.route("**/api/projects/page**", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: 18, name: "Project 18", description: "" }],
        total: 1,
        page: 1,
        page_size: 200,
      }),
    })
  );

  await page.route("**/api/decisions/latest**", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 999,
        project_id: 18,
        status: "success",
        snapshot_date: "2026-02-08",
        summary: {},
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
        created_at: "2026-02-08T00:00:00Z",
        updated_at: "2026-02-08T00:00:00Z",
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
        last_heartbeat: "2026-02-08T00:00:00Z",
        updated_at: "2026-02-08T00:00:00Z",
      }),
    })
  );

  await page.route("**/api/brokerage/stream/status", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "connected",
        last_heartbeat: "2026-02-08T00:00:00Z",
        subscribed_symbols: [],
        ib_error_count: 0,
        last_error: null,
        market_data_type: "delayed",
      }),
    })
  );

  await page.route("**/api/brokerage/bridge/status", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        stale: false,
        last_heartbeat: "2026-02-08T00:00:00Z",
        updated_at: "2026-02-08T00:00:00Z",
      }),
    })
  );

  await page.route("**/api/brokerage/account/summary**", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ name: "NetLiquidation", value: 1000 }],
        refreshed_at: "2026-02-08T00:00:00Z",
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
        refreshed_at: "2026-02-08T00:00:00Z",
        stale: false,
      }),
    })
  );

  await page.route("**/api/brokerage/history-jobs**", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );

  await page.route("**/api/brokerage/contracts/refresh", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 0,
        updated: 0,
        skipped: 0,
        errors: [],
        duration_sec: 0,
      }),
    })
  );

  await page.route("**/api/brokerage/market/health", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        total: 0,
        success: 0,
        missing_symbols: [],
        errors: [],
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

  // Handle /api/trade/runs list + detail + symbols in one route to avoid glob ordering issues.
  await page.route("**/api/trade/runs**", async (route: any) => {
    const url = route.request().url();
    if (/\/api\/trade\/runs\/\d+\/detail/.test(url)) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          run: {
            id: 10,
            project_id: 18,
            decision_snapshot_id: 999,
            mode: "paper",
            status: "running",
            params: {},
            created_at: "2026-02-08T00:00:00Z",
          },
          orders: [],
          fills: [
            {
              id: 1,
              order_id: 101,
              symbol: "AAPL",
              side: "BUY",
              exec_id: "EXEC-101",
              fill_quantity: 1,
              fill_price: 100,
              commission: 0.1,
              realized_pnl: 0,
              exchange: "SMART",
              fill_time: "2026-02-08T01:00:00Z",
            },
            {
              id: 2,
              order_id: 303,
              symbol: "SPY",
              side: "BUY",
              exec_id: "EXEC-303",
              fill_quantity: 1,
              fill_price: 400,
              commission: 0.1,
              realized_pnl: 0,
              exchange: "SMART",
              fill_time: "2026-02-08T01:02:00Z",
            },
            {
              id: 3,
              order_id: 202,
              symbol: "MSFT",
              side: "BUY",
              exec_id: "EXEC-202",
              fill_quantity: 1,
              fill_price: 200,
              commission: 0.1,
              realized_pnl: 0,
              exchange: "SMART",
              fill_time: "2026-02-08T01:01:00Z",
            },
          ],
          last_update_at: "2026-02-08T01:03:00Z",
        }),
      });
      return;
    }
    if (/\/api\/trade\/runs\/\d+\/symbols/.test(url)) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], last_update_at: "2026-02-08T01:03:00Z" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 10,
          project_id: 18,
          decision_snapshot_id: 999,
          mode: "paper",
          status: "running",
          params: {},
          created_at: "2026-02-08T00:00:00Z",
        },
      ]),
    });
  });

  await page.route("**/api/trade/guard**", (route: any) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        project_id: 18,
        trade_date: "2026-02-08",
        mode: "paper",
        status: "ok",
        risk_triggers: 0,
        order_failures: 0,
        market_data_errors: 0,
      }),
    })
  );

  await page.route("**/api/trade/orders**", (route: any) =>
    route.fulfill({
      status: 200,
      headers: { "x-total-count": "3" },
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 101,
          run_id: 10,
          client_order_id: "oi_10_0",
          symbol: "AAPL",
          side: "BUY",
          quantity: 1,
          order_type: "LMT",
          limit_price: 100,
          status: "SUBMITTED",
          created_at: "2026-02-08T00:10:00Z",
        },
        {
          id: 303,
          run_id: 10,
          client_order_id: "oi_10_2",
          symbol: "SPY",
          side: "BUY",
          quantity: 1,
          order_type: "LMT",
          limit_price: 400,
          status: "SUBMITTED",
          created_at: "2026-02-08T00:12:00Z",
        },
        {
          id: 202,
          run_id: 10,
          client_order_id: "oi_10_1",
          symbol: "MSFT",
          side: "BUY",
          quantity: 1,
          order_type: "LMT",
          limit_price: 200,
          status: "SUBMITTED",
          created_at: "2026-02-08T00:11:00Z",
        },
      ]),
    })
  );

  await page.route("**/api/trade/receipts**", (route: any) =>
    route.fulfill({
      status: 200,
      headers: { "x-total-count": "3" },
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            time: "2026-02-08T01:01:00Z",
            kind: "submit",
            order_id: 101,
            client_order_id: "oi_10_0",
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
            time: "2026-02-08T01:02:00Z",
            kind: "submit",
            order_id: 303,
            client_order_id: "oi_10_2",
            symbol: "SPY",
            side: "BUY",
            quantity: 1,
            filled_quantity: 0,
            fill_price: null,
            exec_id: null,
            status: "SUBMITTED",
            source: "lean",
          },
          {
            time: "2026-02-08T01:01:30Z",
            kind: "submit",
            order_id: 202,
            client_order_id: "oi_10_1",
            symbol: "MSFT",
            side: "BUY",
            quantity: 1,
            filled_quantity: 0,
            fill_price: null,
            exec_id: null,
            status: "SUBMITTED",
            source: "lean",
          },
        ],
        total: 3,
        warnings: [],
      }),
    })
  );
};

test("live trade monitor tables sort by order id desc", async ({ page }) => {
  await mockApi(page);
  await page.goto("/live-trade");

  await page.getByTestId("trade-tab-orders").click();
  const firstOrderIdCell = page
    .locator('[data-testid="trade-orders-table"] tbody tr')
    .first()
    .locator("td")
    .first();
  await expect(firstOrderIdCell).toHaveText("#303");

  await page.getByTestId("trade-tab-fills").click();
  const firstFillOrderIdCell = page
    .locator('[data-testid="trade-fills-table"] tbody tr')
    .first()
    .locator("td")
    .first();
  await expect(firstFillOrderIdCell).toHaveText("#303");

  await page.getByTestId("trade-tab-receipts").click();
  const firstReceiptOrderIdCell = page
    .locator('[data-testid="trade-receipts-table"] tbody tr')
    .first()
    .locator("td")
    .nth(2);
  await expect(firstReceiptOrderIdCell).toHaveText("#303");
});
