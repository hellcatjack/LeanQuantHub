import { expect, test } from "@playwright/test";

const corsHeaders = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
  "access-control-allow-headers": "*",
};

const jsonResponse = (
  body: unknown,
  extraHeaders?: Record<string, string>,
) => ({
  status: 200,
  contentType: "application/json",
  headers: { ...corsHeaders, ...extraHeaders },
  body: JSON.stringify(body),
});

const mockLiveTradePositionChartApi = async (page: any) => {
  await page.route("**/api/**", async (route: any) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
      return;
    }

    const url = new URL(request.url());
    const path = url.pathname;

    if (path.endsWith("/api/projects/page")) {
      await route.fulfill(
        jsonResponse({
          items: [{ id: 18, name: "Position Chart Project" }],
          total: 1,
          page: 1,
          page_size: 200,
        }),
      );
      return;
    }

    if (path.endsWith("/api/decisions/latest")) {
      await route.fulfill(
        jsonResponse({
          id: 91,
          project_id: 18,
          status: "success",
          snapshot_date: "2026-03-10",
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/settings")) {
      await route.fulfill(
        jsonResponse({
          id: 1,
          host: "127.0.0.1",
          port: 7497,
          workstation_type: "gateway",
          client_id: 1,
          account_id: "DU123456",
          mode: "paper",
          market_data_type: "delayed",
          api_mode: "ib",
          use_regulatory_snapshot: false,
          created_at: "2026-03-10T14:00:00Z",
          updated_at: "2026-03-10T14:00:00Z",
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/state")) {
      await route.fulfill(
        jsonResponse({
          id: 1,
          status: "connected",
          message: "ok",
          last_heartbeat: "2026-03-10T14:00:00Z",
          updated_at: "2026-03-10T14:00:00Z",
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/stream/status")) {
      await route.fulfill(
        jsonResponse({
          status: "connected",
          last_heartbeat: "2026-03-10T14:00:00Z",
          subscribed_symbols: ["AAPL", "MSFT"],
          ib_error_count: 0,
          last_error: null,
          market_data_type: "delayed",
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/bridge/status")) {
      await route.fulfill(
        jsonResponse({
          status: "ok",
          stale: false,
          last_heartbeat: "2026-03-10T14:00:00Z",
          updated_at: "2026-03-10T14:00:00Z",
          runtime_health: {
            state: "healthy",
            last_probe_result: "success",
            last_probe_latency_ms: 110,
          },
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/account/summary")) {
      await route.fulfill(
        jsonResponse({
          items: {
            NetLiquidation: "100000",
            AvailableFunds: "50000",
          },
          refreshed_at: "2026-03-10T14:00:00Z",
          source: "lean_bridge",
          stale: false,
          full: false,
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/account/positions")) {
      await route.fulfill(
        jsonResponse({
          items: [
            {
              symbol: "AAPL",
              position: 10,
              avg_cost: 175.5,
              market_price: 178.2,
              market_value: 1782,
              unrealized_pnl: 27,
              realized_pnl: 0,
              account: "DU123456",
              currency: "USD",
            },
            {
              symbol: "MSFT",
              position: 5,
              avg_cost: 410.2,
              market_price: 415.1,
              market_value: 2075.5,
              unrealized_pnl: 24.5,
              realized_pnl: 0,
              account: "DU123456",
              currency: "USD",
            },
          ],
          refreshed_at: "2026-03-10T14:00:00Z",
          stale: false,
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/history/chart")) {
      const symbol = url.searchParams.get("symbol") || "AAPL";
      const interval = url.searchParams.get("interval") || "1D";
      if (symbol === "AAPL" && interval === "1m") {
        await route.fulfill(
          jsonResponse({
            symbol: "AAPL",
            interval: "1m",
            source: "unavailable",
            fallback_used: false,
            stale: false,
            bars: [],
            markers: [],
            meta: {
              price_precision: 2,
              currency: "USD",
              range_label: "1D",
              last_bar_at: null,
            },
            error: "ib_history_unavailable",
          }),
        );
        return;
      }
      if (symbol === "AAPL") {
        await route.fulfill(
          jsonResponse({
            symbol: "AAPL",
            interval,
            source: "local",
            fallback_used: true,
            stale: false,
            bars: [
              {
                time: 1773097200,
                open: 189.5,
                high: 191.0,
                low: 188.2,
                close: 190.8,
                volume: 1500000,
              },
              {
                time: 1773356400,
                open: 191.1,
                high: 193.3,
                low: 190.7,
                close: 192.4,
                volume: 1800000,
              },
            ],
            markers: [],
            meta: {
              price_precision: 2,
              currency: "USD",
              range_label: "6M",
              last_bar_at: "2026-03-10T20:00:00Z",
            },
            error: null,
          }),
        );
        return;
      }
      await route.fulfill(
        jsonResponse({
          symbol: "MSFT",
          interval,
          source: "ib",
          fallback_used: false,
          stale: false,
          bars: [
            {
              time: 1773097200,
              open: 410.0,
              high: 412.4,
              low: 408.3,
              close: 411.5,
              volume: 1200000,
            },
            {
              time: 1773356400,
              open: 412.1,
              high: 416.2,
              low: 411.4,
              close: 415.1,
              volume: 1350000,
            },
          ],
          markers: [],
          meta: {
            price_precision: 2,
            currency: "USD",
            range_label: interval === "1m" ? "1D" : "6M",
            last_bar_at: "2026-03-10T20:00:00Z",
          },
          error: null,
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/history-jobs")) {
      await route.fulfill(jsonResponse([]));
      return;
    }

    if (path.endsWith("/api/brokerage/stream/snapshot")) {
      await route.fulfill(
        jsonResponse({
          symbol: "AAPL",
          data: { last: 178.2, close: 178.0, volume: 1000 },
          error: null,
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/contracts/refresh")) {
      await route.fulfill(
        jsonResponse({
          total: 0,
          updated: 0,
          skipped: 0,
          errors: [],
          duration_sec: 0.1,
        }),
      );
      return;
    }

    if (path.endsWith("/api/brokerage/market/health")) {
      await route.fulfill(
        jsonResponse({
          status: "ok",
          total: 2,
          success: 2,
          missing_symbols: [],
          errors: [],
        }),
      );
      return;
    }

    if (path.endsWith("/api/trade/settings")) {
      await route.fulfill(jsonResponse({}));
      return;
    }

    if (path.endsWith("/api/trade/runs")) {
      await route.fulfill(jsonResponse([]));
      return;
    }

    if (path.endsWith("/api/trade/orders")) {
      await route.fulfill(jsonResponse([], { "x-total-count": "0" }));
      return;
    }

    if (path.endsWith("/api/trade/receipts")) {
      await route.fulfill(
        jsonResponse(
          { items: [], total: 0, warnings: [] },
          { "x-total-count": "0" },
        ),
      );
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      headers: corsHeaders,
      body: JSON.stringify({ detail: `unmocked route: ${path}` }),
    });
  });
};

test("live trade position chart workspace supports fallback and intraday unavailable states", async ({
  page,
}) => {
  await mockLiveTradePositionChartApi(page);

  await page.goto("/live-trade");

  await expect(page.getByTestId("account-positions-table")).toBeVisible();
  await expect(page.getByTestId("position-chart-workspace")).toBeVisible();
  await expect(page.getByTestId("position-chart-symbol-label")).toContainText(
    "AAPL",
  );
  await expect(page.getByTestId("position-chart-fallback-badge")).toContainText(
    /回退|Fallback/,
  );
  await expect(page.getByTestId("position-chart-status-banner")).toContainText(
    /本地日线回退|local daily fallback/i,
  );

  await page.getByTestId("position-chart-symbol-MSFT").click();
  await expect(page.getByTestId("position-chart-symbol-label")).toContainText(
    "MSFT",
  );
  await expect(page.getByTestId("position-chart-workspace")).toContainText(
    /IB History|IB 历史/,
  );

  await page.getByTestId("position-chart-symbol-AAPL").click();
  await page.getByTestId("position-chart-interval-1m").click();
  await expect(page.getByTestId("position-chart-overlay")).toContainText(
    /需要 IB 历史数据|requires IB historical data/i,
  );

  await page.getByTestId("position-chart-interval-1D").click();
  await expect(page.getByTestId("position-chart-fallback-badge")).toBeVisible();
});

test("live trade positions keep rows single-line and float chart away from selected row on desktop", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1200 });
  await mockLiveTradePositionChartApi(page);

  await page.goto("/live-trade");
  await expect(page.getByTestId("account-positions-table")).toBeVisible();
  await expect(page.getByTestId("position-chart-workspace")).toBeVisible();

  const layout = await page.evaluate(() => {
    const card = document.querySelector(
      '[data-testid="account-positions-card"]',
    );
    const chartPane = card?.querySelector(
      '[data-testid="position-chart-workspace"]',
    );
    const firstRow = card?.querySelector(".positions-table tbody tr");
    const symbolCell = firstRow?.querySelector("td:nth-child(2)");
    const actionToolbar = firstRow?.querySelector(
      '[data-testid="positions-action-toolbar-AAPL"]',
    );

    if (!card || !chartPane || !firstRow || !symbolCell || !actionToolbar) {
      return null;
    }

    const cardRect = card.getBoundingClientRect();
    const chartRect = chartPane.getBoundingClientRect();
    const rowRect = firstRow.getBoundingClientRect();
    const symbolRect = symbolCell.getBoundingClientRect();
    const toolbarRect = actionToolbar.getBoundingClientRect();

    const rowClear =
      chartRect.bottom <= rowRect.top || chartRect.top >= rowRect.bottom;
    return {
      cardWidth: cardRect.width,
      rowHeight: rowRect.height,
      floating: getComputedStyle(chartPane).position === "absolute",
      rowClear,
      preservesSymbolColumn: chartRect.left > symbolRect.right + 40,
      toolbarSingleLine: toolbarRect.height < 34,
    };
  });

  expect(layout).not.toBeNull();
  expect(layout?.cardWidth ?? 0).toBeGreaterThan(1000);
  expect(layout?.floating).toBe(true);
  expect(layout?.rowClear).toBe(true);
  expect(layout?.preservesSymbolColumn).toBe(true);
  expect(layout?.toolbarSingleLine).toBe(true);
  expect(layout?.rowHeight ?? 0).toBeLessThan(56);
});

test("live trade floating chart remembers drag position, supports minimize, and restores resized window", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1200 });
  await mockLiveTradePositionChartApi(page);

  await page.goto("/live-trade");
  const chart = page.getByTestId("position-chart-workspace");
  await expect(chart).toBeVisible();

  const before = await chart.boundingBox();
  expect(before).not.toBeNull();

  await page.getByTestId("position-chart-drag-handle").hover();
  await page.mouse.down();
  await page.waitForTimeout(60);
  await page.mouse.move((before?.x ?? 0) - 220, (before?.y ?? 0) + 120, {
    steps: 8,
  });
  await page.mouse.up();
  await page.waitForTimeout(80);

  const afterDrag = await chart.boundingBox();
  expect(afterDrag).not.toBeNull();
  expect(afterDrag?.x ?? 0).toBeLessThan((before?.x ?? 0) - 80);

  const resizeHandle = page.getByTestId("position-chart-resize-handle");
  const handleBox = await resizeHandle.boundingBox();
  expect(handleBox).not.toBeNull();
  const resizeStartX = (handleBox?.x ?? 0) + (handleBox?.width ?? 0) / 2;
  const resizeStartY = (handleBox?.y ?? 0) + (handleBox?.height ?? 0) / 2;
  const resizeEndX = (afterDrag?.x ?? 0) + (afterDrag?.width ?? 0) + 140;
  const resizeEndY = (afterDrag?.y ?? 0) + (afterDrag?.height ?? 0) + 80;

  await resizeHandle.dispatchEvent("pointerdown", {
    pointerId: 11,
    bubbles: true,
    clientX: resizeStartX,
    clientY: resizeStartY,
  });
  await page.evaluate(
    ({ endX, endY }) => {
      window.dispatchEvent(
        new PointerEvent("pointermove", {
          pointerId: 11,
          bubbles: true,
          clientX: endX,
          clientY: endY,
        }),
      );
      window.dispatchEvent(
        new PointerEvent("pointerup", {
          pointerId: 11,
          bubbles: true,
          clientX: endX,
          clientY: endY,
        }),
      );
    },
    { endX: resizeEndX, endY: resizeEndY },
  );
  await page.waitForTimeout(120);

  const afterResize = await chart.boundingBox();
  expect(afterResize).not.toBeNull();
  expect(afterResize?.width ?? 0).toBeGreaterThan((afterDrag?.width ?? 0) + 40);

  await page.getByTestId("position-chart-minimize-toggle").click();
  await expect(page.getByTestId("position-chart-workspace")).toHaveAttribute(
    "data-minimized",
    "true",
  );
  await expect(page.getByTestId("position-chart-toolbar")).toBeHidden();

  await page.getByTestId("position-chart-minimize-toggle").click();
  await expect(page.getByTestId("position-chart-workspace")).toHaveAttribute(
    "data-minimized",
    "false",
  );

  await page.reload();
  await expect(chart).toBeVisible();

  const afterReload = await chart.boundingBox();
  expect(afterReload).not.toBeNull();
  expect(Math.abs((afterReload?.x ?? 0) - (afterResize?.x ?? 0))).toBeLessThan(
    8,
  );
  expect(
    Math.abs((afterReload?.width ?? 0) - (afterResize?.width ?? 0)),
  ).toBeLessThan(8);
});

test("live trade positions stack chart below table on narrower viewports", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1180, height: 1200 });
  await mockLiveTradePositionChartApi(page);

  await page.goto("/live-trade");
  await expect(page.getByTestId("account-positions-table")).toBeVisible();
  await expect(page.getByTestId("position-chart-workspace")).toBeVisible();

  const layout = await page.evaluate(() => {
    const card = document.querySelector(
      '[data-testid="account-positions-card"]',
    );
    const tablePane = card?.querySelector(".positions-table-pane");
    const chartPane = card?.querySelector(
      '[data-testid="position-chart-workspace"]',
    );
    if (!card || !tablePane || !chartPane) {
      return null;
    }
    const tableRect = tablePane.getBoundingClientRect();
    const chartRect = chartPane.getBoundingClientRect();
    return {
      floating: getComputedStyle(chartPane).position === "absolute",
      chartBelowTable: chartRect.top > tableRect.bottom - 1,
    };
  });

  expect(layout).not.toBeNull();
  expect(layout?.floating).toBe(false);
  expect(layout?.chartBelowTable).toBe(true);
});
