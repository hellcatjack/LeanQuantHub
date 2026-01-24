import { test, expect } from "@playwright/test";

test.use({ viewport: { width: 820, height: 800 } });

test("live trade positions table stays within grid", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("locale", "en");
  });

  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/api/ib/settings")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          host: "127.0.0.1",
          port: 4002,
          client_id: 101,
          account_id: "DU123456",
          mode: "paper",
          market_data_type: "realtime",
          api_mode: "ib",
          use_regulatory_snapshot: false,
          updated_at: "2026-01-24T12:00:00Z",
        }),
      });
    }
    if (url.includes("/api/ib/status/overview")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          refreshed_at: "2026-01-24T12:00:00Z",
          stream: { status: "connected", subscribed_count: 5, ib_error_count: 0 },
          snapshot_cache: { status: "ok", last_snapshot_at: "2026-01-24T12:00:00Z" },
          orders: { latest_order_status: "filled", latest_order_at: "2026-01-24T12:00:00Z" },
          alerts: { latest_alert_title: "ok", latest_alert_at: "2026-01-24T12:00:00Z" },
        }),
      });
    }
    if (url.includes("/api/ib/account/summary")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: {
            NetLiquidation: 125000.12,
            TotalCashValue: 64000.55,
            AvailableFunds: 50000.25,
            BuyingPower: 100000.5,
            GrossPositionValue: 61000.12,
          },
          refreshed_at: "2026-01-24T12:00:00Z",
          source: "lean_bridge",
          stale: false,
          full: false,
        }),
      });
    }
    if (url.includes("/api/ib/account/positions")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              symbol: "BRK.B",
              position: 1250.1234,
              avg_cost: 342.88,
              market_price: 355.12,
              market_value: 444000.12,
              unrealized_pnl: 19000.33,
              realized_pnl: 1200.25,
              account: "DU123456789012345",
              currency: "USD",
            },
            {
              symbol: "TSLA",
              position: 230.5,
              avg_cost: 250.12,
              market_price: 260.98,
              market_value: 60120.45,
              unrealized_pnl: 2521.45,
              realized_pnl: 0,
              account: "DU123456789012345",
              currency: "USD",
            },
          ],
          refreshed_at: "2026-01-24T12:00:00Z",
          stale: false,
        }),
      });
    }
    if (url.includes("/api/ib/state")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "connected",
          updated_at: "2026-01-24T12:00:00Z",
        }),
      });
    }
    if (url.includes("/api/ib/stream/status")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "connected",
          last_heartbeat: "2026-01-24T12:00:00Z",
          subscribed_symbols: ["SPY", "AAPL", "MSFT", "BRK.B", "TSLA"],
          ib_error_count: 0,
          last_error: null,
          market_data_type: "realtime",
        }),
      });
    }
    if (url.includes("/api/trade/settings")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 1,
          execution_data_source: "lean",
          paper_enabled: true,
          live_enabled: false,
          updated_at: "2026-01-24T12:00:00Z",
        }),
      });
    }
    if (url.includes("/api/trade/runs")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    }
    if (url.includes("/api/trade/orders")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });

  await page.goto("/live-trade");

  const positionsCard = page.locator(".card", {
    has: page.locator(".card-title", { hasText: "Positions" }),
  });
  await expect(positionsCard).toBeVisible();
  await expect(positionsCard.locator("table")).toBeVisible();

  const cardMinWidth = await positionsCard.evaluate((card) =>
    window.getComputedStyle(card).minWidth
  );
  const scrollMinWidth = await positionsCard
    .locator(".table-scroll")
    .evaluate((el) => window.getComputedStyle(el).minWidth);

  expect(cardMinWidth).toBe("0px");
  expect(scrollMinWidth).toBe("0px");

  const gridOverflow = await positionsCard.evaluate((card) => {
    let node = card.parentElement;
    while (node && !node.classList.contains("grid-2")) {
      node = node.parentElement;
    }
    if (!node) {
      return { scrollWidth: 0, clientWidth: 0 };
    }
    return { scrollWidth: node.scrollWidth, clientWidth: node.clientWidth };
  });

  expect(gridOverflow.scrollWidth).toBeLessThanOrEqual(gridOverflow.clientWidth);
});
