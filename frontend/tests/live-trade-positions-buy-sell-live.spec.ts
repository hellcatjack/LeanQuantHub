import { test, expect } from "@playwright/test";

const shouldRun = process.env.PLAYWRIGHT_LIVE_TRADE === "1";

test("live positions buy/sell submits direct orders", async ({ page }) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1 and live env");
  test.setTimeout(120_000);

  await page.goto("/live-trade");

  const projectSelect = page.getByTestId("live-trade-project-select");
  await expect(projectSelect).toBeVisible();
  await expect
    .poll(async () => (await projectSelect.locator("option").count()) > 1)
    .toBeTruthy();
  const currentValue = await projectSelect.inputValue();
  if (!currentValue) {
    const optionValue = await projectSelect.locator("option").nth(1).getAttribute("value");
    if (optionValue) {
      await projectSelect.selectOption(optionValue);
    }
  }

  await page.getByTestId("account-positions-card").scrollIntoViewIfNeeded();
  const rows = page.getByTestId("account-positions-table").locator("tbody tr");
  await expect(rows.first()).toBeVisible({ timeout: 60_000 });
  const rowCount = await rows.count();
  expect(rowCount).toBeGreaterThan(0);

  const row = rows.first();
  const qtyInput = row.locator("input[type='number']").first();
  await qtyInput.fill("1");
  await row.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, 200));

  const submitAndCapture = async (label: "BUY" | "SELL") => {
    const responsePromise = page.waitForResponse((resp) => {
      return (
        resp.url().includes("/api/trade/orders/direct") &&
        resp.request().method() === "POST"
      );
    });
    page.once("dialog", async (dialog) => {
      await dialog.accept();
    });
    await row.getByRole("button", { name: new RegExp(label, "i") }).click({ force: true });
    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
    const payload = response.request().postDataJSON();
    expect(payload).toMatchObject({
      symbol: payload.symbol,
      side: label,
      quantity: 1,
      order_type: "MKT",
    });
    return response.json();
  };

  const buyResult = await submitAndCapture("BUY");
  const sellResult = await submitAndCapture("SELL");

  expect(buyResult?.order_id).toBeTruthy();
  expect(sellResult?.order_id).toBeTruthy();
});
