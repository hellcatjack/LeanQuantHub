import { test, expect } from "@playwright/test";

test("live trade page shows connection state", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(
    page.locator(".card-title", { hasText: /交易状态|Trading Status/i })
  ).toBeVisible();
});

test("live trade page shows bridge status card", async ({ page }) => {
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
  await page.locator("details.algo-advanced > summary").click();
  await expect(
    page.getByRole("columnheader", { name: /决策快照|Decision Snapshot/i })
  ).toBeVisible();
});

test("live trade page shows ib stream card", async ({ page }) => {
  await page.goto("/live-trade");
  await page.locator("details.algo-advanced > summary").click();
  const healthLabel = page.locator(".overview-label", {
    hasText: /行情源健康|Market Data Health|trade\.marketHealthTitle/i,
  });
  await expect(healthLabel.first()).toBeVisible();
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

test("live trade positions show realized pnl not reported when missing", async ({ page }) => {
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
            realized_pnl: null,
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
  const realizedCell = page
    .getByTestId("account-positions-table")
    .locator("tbody tr td")
    .nth(7);
  await expect(realizedCell).toHaveText(/未回传|Not reported/);
});

test("live trade positions table stays within card width", async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 800 });
  await page.route("**/api/brokerage/account/positions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            symbol: "VERY-LONG-SYMBOL-NAME",
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
  const card = page.locator(".card", { hasText: /当前持仓|Positions/i }).first();
  const tableScroll = card.locator(".table-scroll");
  await expect(tableScroll).toBeVisible();
  const cardBox = await card.boundingBox();
  const scrollBox = await tableScroll.boundingBox();
  expect(cardBox).not.toBeNull();
  expect(scrollBox).not.toBeNull();
  if (!cardBox || !scrollBox) {
    throw new Error("Missing layout metrics");
  }
  expect(scrollBox.width).toBeLessThanOrEqual(cardBox.width + 1);
});

test("live trade positions table does not cause horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 480, height: 800 });
  await page.route("**/api/brokerage/account/positions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            symbol: "LONG-SYMBOL",
            position: 12,
            avg_cost: 420.5,
            market_price: 432.1,
            market_value: 5185.2,
            unrealized_pnl: 139.2,
            realized_pnl: 0.0,
            account: "DU1234567890",
            currency: "USD",
          },
        ],
        refreshed_at: "2026-01-24T00:00:00Z",
        stale: false,
      }),
    })
  );
  await page.goto("/live-trade");
  await page.addStyleTag({
    content: ".sidebar { display: none !important; } .app-shell { grid-template-columns: 1fr !important; }",
  });
  const overflowSize = await page.evaluate(() => {
    const content = document.querySelector(".content");
    if (!content) {
      return Number.POSITIVE_INFINITY;
    }
    return content.scrollWidth - content.clientWidth;
  });
  expect(overflowSize).toBeLessThanOrEqual(120);
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

test("live trade shows id chips in execution context", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: 18, name: "Project 18" }],
        total: 1,
        page: 1,
        page_size: 200,
      }),
    })
  );
  await page.route("**/api/decisions/latest?project_id=18", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 91,
        project_id: 18,
        status: "success",
        snapshot_date: "2026-01-25",
      }),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 88,
          project_id: 18,
          decision_snapshot_id: 91,
          mode: "paper",
          status: "queued",
          created_at: "2026-01-25T00:00:00Z",
        },
      ]),
    })
  );
  await page.goto("/live-trade");
  await page.locator("details.algo-advanced > summary").click();
  await expect(
    page.locator(".id-chip-text", { hasText: /项目#18|Project#18/i })
  ).toBeVisible();
  await expect(
    page.locator(".id-chip-text", { hasText: /快照#91|Snapshot#91/i }).first()
  ).toBeVisible();
  await expect(
    page.locator(".id-chip-text", { hasText: /批次#88|Run#88/i }).first()
  ).toBeVisible();
});

test("project binding: requires project before execute", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 200 }),
    })
  );
  await page.route("**/api/decisions/latest**", (route) => route.abort());
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.goto("/live-trade");
  await expect(
    page.locator(".form-hint", { hasText: /请选择项目|Select a project/i })
  ).toBeVisible();
  await expect(page.locator("button", { hasText: /执行交易|Execute/i })).toBeDisabled();
});

test("project binding: snapshot missing disables execute", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: 18, name: "Project 18" }],
        total: 1,
        page: 1,
        page_size: 200,
      }),
    })
  );
  await page.route("**/api/decisions/latest**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "snapshot not found" }),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.goto("/live-trade");
  await expect(
    page.locator(".form-hint", { hasText: /未生成快照|Snapshot not generated/i })
  ).toBeVisible();
  await expect(page.locator("button", { hasText: /执行交易|Execute/i })).toBeDisabled();
});

test("project binding: snapshot present enables execute", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: 18, name: "Project 18" }],
        total: 1,
        page: 1,
        page_size: 200,
      }),
    })
  );
  await page.route("**/api/decisions/latest?project_id=18", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 91,
        project_id: 18,
        status: "success",
        snapshot_date: "2026-01-25",
        summary: { total_items: 42, version: "v1" },
      }),
    })
  );
  await page.route("**/api/trade/runs**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    })
  );
  await page.goto("/live-trade");
  await expect(
    page.locator(".meta-row", { hasText: /快照日期|Snapshot date/i })
  ).toBeVisible();
  await expect(page.locator("button", { hasText: /执行交易|Execute/i })).not.toBeDisabled();
});
