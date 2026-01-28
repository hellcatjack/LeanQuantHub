import { test, expect } from "@playwright/test";

const shouldRun = process.env.PLAYWRIGHT_LIVE_TRADE === "1";

test("manual buy/sell triggers trade orders", async ({ page }) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1");
  await page.goto("/live-trade");
  const table = page.getByTestId("account-positions-table");
  await expect(table).toBeVisible();
  const row = table.locator("tbody tr").first();
  await row.locator("input[type=number]").fill("1");
  const buyRequest = page.waitForRequest((req) => {
    return req.url().includes("/api/trade/orders") && req.method() === "POST";
  });
  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: /买入|Buy/i }).click();
  const req = await buyRequest;
  const payload = JSON.parse(req.postData() || "{}");
  expect(payload.params?.source).toBe("manual");
  expect(payload.params?.project_id).toBeTruthy();
  expect(payload.params?.mode).toBeTruthy();

  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: /卖出|Sell/i }).click();
});
