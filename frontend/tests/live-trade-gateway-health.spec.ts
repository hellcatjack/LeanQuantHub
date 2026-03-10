import { expect, test } from "@playwright/test";

const corsHeaders = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
  "access-control-allow-headers": "*",
};

const jsonResponse = (body: unknown, extraHeaders?: Record<string, string>) => ({
  status: 200,
  contentType: "application/json",
  headers: { ...corsHeaders, ...extraHeaders },
  body: JSON.stringify(body),
});

const mockLiveTradeGatewayRecoveryApi = async (page: any) => {
  let positionsCallCount = 0;

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
          items: [{ id: 18, name: "Gateway Recovery Project" }],
          total: 1,
          page: 1,
          page_size: 200,
        })
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
        })
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
        })
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
        })
      );
      return;
    }

    if (path.endsWith("/api/brokerage/stream/status")) {
      await route.fulfill(
        jsonResponse({
          status: "connected",
          last_heartbeat: "2026-03-10T14:00:00Z",
          subscribed_symbols: ["AAPL"],
          ib_error_count: 0,
          last_error: null,
          market_data_type: "delayed",
        })
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
          last_refresh_at: "2026-03-10T14:01:00Z",
          last_refresh_result: "success",
          last_refresh_reason: "auto",
          runtime_health: {
            state: "gateway_restarting",
            last_probe_result: "failure",
            last_probe_latency_ms: 350,
            last_recovery_action: "gateway_restart",
            last_recovery_at: "2026-03-10T14:02:00Z",
            next_allowed_action_at: "2026-03-10T14:17:00Z",
          },
        })
      );
      return;
    }

    if (path.endsWith("/api/brokerage/bridge/refresh")) {
      await route.fulfill(
        jsonResponse({
          bridge_status: {
            status: "ok",
            stale: false,
            runtime_health: {
              state: "gateway_restarting",
              last_probe_result: "failure",
              last_probe_latency_ms: 350,
              last_recovery_action: "gateway_restart",
              last_recovery_at: "2026-03-10T14:02:00Z",
              next_allowed_action_at: "2026-03-10T14:17:00Z",
            },
          },
        })
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
        })
      );
      return;
    }

    if (path.endsWith("/api/brokerage/account/positions")) {
      positionsCallCount += 1;
      if (positionsCallCount === 1) {
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
            ],
            refreshed_at: "2026-03-10T14:00:00Z",
            stale: false,
          })
        );
        return;
      }
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        headers: corsHeaders,
        body: JSON.stringify({ detail: "positions unavailable" }),
      });
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
        })
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
        })
      );
      return;
    }

    if (path.endsWith("/api/brokerage/market/health")) {
      await route.fulfill(
        jsonResponse({
          status: "ok",
          total: 1,
          success: 1,
          missing_symbols: [],
          errors: [],
        })
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
        jsonResponse({ items: [], total: 0, warnings: [] }, { "x-total-count": "0" })
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

  return {
    getPositionsCallCount: () => positionsCallCount,
  };
};

test("live trade keeps trusted positions and blocks new execution during gateway restart", async ({
  page,
}) => {
  const apiState = await mockLiveTradeGatewayRecoveryApi(page);

  await page.goto("/live-trade");

  const positionsTable = page.getByTestId("account-positions-table");
  await expect(positionsTable).toBeVisible();
  await expect(positionsTable.locator("tbody tr")).toContainText("AAPL");

  const executeButton = page.getByTestId("paper-trade-execute");
  await expect(executeButton).toBeDisabled();
  await expect(page.getByTestId("gateway-runtime-row")).toContainText(
    /重启中|Restarting|Gateway Restarting/
  );

  const firstBuyButton = positionsTable.getByRole("button", { name: /买入|Buy/i }).first();
  await expect(firstBuyButton).toBeDisabled();
  await expect(page.getByTestId("gateway-trade-block-banner")).toContainText(
    /自动重启|restarting automatically|禁止新批次/
  );

  await page.getByTestId("live-trade-auto-toggle").click();
  await page.getByTestId("live-trade-refresh-all").click();
  await expect.poll(() => apiState.getPositionsCallCount()).toBeGreaterThanOrEqual(2);

  await expect(positionsTable.locator("tbody tr")).toContainText("AAPL");
  await expect(page.getByTestId("positions-trusted-fallback-banner")).toContainText(
    /最后一次可信持仓|last trusted positions/i
  );
  await expect(page.getByText(/positions unavailable/i)).toBeVisible();
});
