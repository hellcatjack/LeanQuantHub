import { test, expect } from "@playwright/test";

test("positions table supports select + batch close", async ({ page }) => {
  await page.goto("/live-trade");
  await page.getByTestId("account-positions-card").scrollIntoViewIfNeeded();

  const firstRow = page.getByTestId("account-positions-table").locator("tbody tr").first();
  await firstRow.getByRole("checkbox").check();

  let dialogMessage = "";
  page.once("dialog", async (dialog) => {
    dialogMessage = dialog.message();
    await dialog.accept();
  });
  await page.getByTestId("positions-batch-close").click();
  expect(dialogMessage).toMatch(/批量平仓|Batch Close|Confirm batch close/);
  await expect(page.getByText(/oi_/).first()).toBeVisible({ timeout: 30000 });

  let buyDialog = "";
  const buyRequestPromise = page.waitForRequest((req) =>
    req.method() === "POST" && req.url().includes("/api/trade/orders/direct")
  );
  page.once("dialog", async (dialog) => {
    buyDialog = dialog.message();
    await dialog.accept();
  });
  await firstRow.getByRole("button", { name: /买入|Buy/ }).click();
  expect(buyDialog).toMatch(/买入|BUY|Buy/);
  const buyRequest = await buyRequestPromise;
  const buyPayload = buyRequest.postDataJSON() as { side?: string };
  expect(buyPayload.side).toBe("BUY");

  let sellDialog = "";
  const sellRequestPromise = page.waitForRequest((req) =>
    req.method() === "POST" && req.url().includes("/api/trade/orders/direct")
  );
  page.once("dialog", async (dialog) => {
    sellDialog = dialog.message();
    await dialog.accept();
  });
  await firstRow.getByRole("button", { name: /卖出|Sell/ }).click();
  expect(sellDialog).toMatch(/卖出|SELL|Sell/);
  const sellRequest = await sellRequestPromise;
  const sellPayload = sellRequest.postDataJSON() as { side?: string };
  expect(sellPayload.side).toBe("SELL");
});
