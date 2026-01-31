import { test, expect } from "@playwright/test";

const fulfillJson = (route, body, headers = {}) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    headers,
    body: JSON.stringify(body),
  });

test("positions table buy/sell submits direct orders", async ({ page }) => {
  const orders: any[] = [];

  await page.route("**/api/trade/orders/direct", (route) => {
    orders.push(route.request().postDataJSON());
    return fulfillJson(route, {
      order_id: 1,
      status: "NEW",
      execution_status: "submitted_lean",
      intent_path: "/tmp/intent.json",
      config_path: "/tmp/config.json",
    });
  });

  const dialogMessages: string[] = [];
  page.on("dialog", async (dialog) => {
    dialogMessages.push(dialog.message());
    await dialog.accept();
  });

  await page.goto("/live-trade");
  await page.waitForResponse(
    (res) =>
      res.url().includes("/api/brokerage/account/positions") && res.status() === 200
  );
  const positionsCard = page.getByTestId("account-positions-card");
  await expect(positionsCard).toBeVisible();
  const rows = page.getByTestId("account-positions-table").locator("tbody tr");
  await expect(rows).not.toHaveCount(0, { timeout: 60_000 });

  const row = rows.first();
  const symbol = (await row.locator("td").nth(1).innerText()).trim();
  const qtyInput = row.locator("input.positions-action-input");
  await qtyInput.fill("1");
  await row.getByRole("button", { name: /买入|Buy/i }).click();
  await expect.poll(() => orders.length).toBe(1);

  await row.getByRole("button", { name: /卖出|Sell/i }).click();
  await expect.poll(() => orders.length).toBe(2);

  expect(dialogMessages[0]).toMatch(/BUY|买入|Buy/);
  expect(dialogMessages[1]).toMatch(/SELL|卖出|Sell/);

  expect(orders[0]).toMatchObject({
    symbol,
    side: "BUY",
    quantity: 1,
    order_type: "MKT",
  });
  expect(orders[0].client_order_id).toMatch(/^oi_/);

  expect(orders[1]).toMatchObject({
    symbol,
    side: "SELL",
    quantity: 1,
    order_type: "MKT",
  });
  expect(orders[1].client_order_id).toMatch(/^oi_/);
});
