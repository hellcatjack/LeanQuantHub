import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const bridgePayload = {
    status: "ok",
    stale: false,
    last_heartbeat: "2026-01-24T00:00:00Z",
    updated_at: "2026-01-24T00:00:00Z",
    last_refresh_at: "2026-01-24T00:00:00Z",
    last_refresh_result: "success",
    last_refresh_reason: "auto",
    last_refresh_message: null,
    last_error: null,
  };
  await page.route("**/api/brokerage/bridge/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(bridgePayload),
    })
  );
  await page.route("**/api/brokerage/bridge/refresh**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ bridge_status: bridgePayload }),
    })
  );
});

test("live trade page shows connection state", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(
    page.locator(".card-title", { hasText: /交易状态|Trading Status/i })
  ).toBeVisible();
});

test("live trade shows single refresh control and auto toggle", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByTestId("live-trade-refresh-all")).toBeVisible();
  await expect(page.getByTestId("live-trade-auto-toggle")).toBeVisible();
  const count = await page.locator("[data-testid^=card-refresh-next]").count();
  expect(count).toBeGreaterThanOrEqual(5);
});

test("live trade cards show refresh interval and next time", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByTestId("card-refresh-interval-account")).toBeVisible();
  await expect(page.getByTestId("card-refresh-next-account")).toBeVisible();
});

test("live trade has single refresh button", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByRole("button", { name: /刷新全部|Refresh All/i })).toHaveCount(1);
});

test("refresh all triggers manual health and contract checks", async ({ page }) => {
  let healthHits = 0;
  let contractHits = 0;
  await page.route("**/api/brokerage/market/health", (route) => {
    healthHits += 1;
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
    });
  });
  await page.route("**/api/brokerage/contracts/refresh", (route) => {
    contractHits += 1;
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 0,
        updated: 0,
        skipped: 0,
        errors: [],
        duration_sec: 0.1,
      }),
    });
  });
  await page.goto("/live-trade");
  await page.getByTestId("live-trade-auto-toggle").click();
  healthHits = 0;
  contractHits = 0;
  await page.getByTestId("live-trade-refresh-all").click();
  await expect.poll(() => healthHits).toBeGreaterThan(0);
  await expect.poll(() => contractHits).toBeGreaterThan(0);
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
    page.locator(".form-label", { hasText: /Lean Bridge 状态|Lean Bridge Status/i })
  ).toBeVisible();
});

test("live trade does not show per-bridge refresh button", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(
    page.getByRole("button", { name: /刷新 Lean Bridge|Refresh Lean Bridge/i })
  ).toHaveCount(0);
});

test("live trade main row keeps positions widest", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 900 });
  await page.goto("/live-trade");
  await page.waitForTimeout(1000);
  const widths = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll(".live-trade-main-row .card"));
    return cards.slice(0, 3).map((card) => Math.round(card.getBoundingClientRect().width));
  });
  const contentWidths = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll(".live-trade-main-row .card"));
    return cards.slice(0, 3).map((card) => {
      const styles = window.getComputedStyle(card);
      const paddingLeft = parseFloat(styles.paddingLeft) || 0;
      const paddingRight = parseFloat(styles.paddingRight) || 0;
      return Math.round(card.clientWidth - paddingLeft - paddingRight);
    });
  });
  expect(widths.length).toBeGreaterThanOrEqual(3);
  expect(contentWidths.length).toBeGreaterThanOrEqual(3);
  expect(widths[0]).toBeGreaterThanOrEqual(280);
  expect(widths[1]).toBeGreaterThanOrEqual(280);
  expect(widths[2]).toBeGreaterThan(widths[0]);
  expect(contentWidths[0]).toBeGreaterThanOrEqual(280);
  expect(contentWidths[1]).toBeGreaterThanOrEqual(280);
});

test("refresh all forces bridge refresh", async ({ page }) => {
  await page.unroute("**/api/brokerage/bridge/refresh**");
  let forceParam: string | null = null;
  await page.route("**/api/brokerage/bridge/refresh**", (route) => {
    const url = new URL(route.request().url());
    forceParam = url.searchParams.get("force");
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ bridge_status: { status: "ok", stale: false } }),
    });
  });
  await page.goto("/live-trade");
  await page.getByTestId("live-trade-refresh-all").click();
  await expect.poll(() => forceParam).toBe("true");
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
  const table = page
    .getByTestId("account-positions-card")
    .locator(".table-scroll");
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

test("live trade order submission uses direct order endpoint", async ({ page }) => {
  await page.route("**/api/projects/page**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: 1, name: "Demo", description: "" }],
        total: 1,
        page: 1,
        page_size: 200,
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
  await page.route("**/api/brokerage/account/positions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            symbol: "AAPL",
            position: 1,
            avg_cost: 150,
            market_price: 151.2,
            market_value: 151.2,
            unrealized_pnl: 1.2,
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
      headers: { "x-total-count": "0" },
    })
  );
  let submittedPayload: Record<string, any> | null = null;
  await page.route("**/api/trade/orders/direct", async (route) => {
    submittedPayload = route.request().postDataJSON() as Record<string, any>;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        order_id: 1,
        status: "NEW",
        execution_status: "submitted_lean",
        bridge_status: {
          status: "ok",
          stale: true,
          last_refresh_result: "failed",
          last_refresh_reason: "rate_limited",
        },
        refresh_result: "failed",
      }),
    });
  });
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/live-trade");
  const buyButton = page.getByRole("button", { name: /买入|Buy/i }).first();
  await expect(buyButton).toBeVisible();
  await buyButton.click();
  await expect(
    page.getByText(/已提交\\s*\\d+\\s*笔订单|orders submitted/i)
  ).toBeVisible();
  await expect(page.locator(".form-hint.warn")).toContainText(/Lean Bridge/i);
  expect(submittedPayload?.symbol).toBe("AAPL");
});
