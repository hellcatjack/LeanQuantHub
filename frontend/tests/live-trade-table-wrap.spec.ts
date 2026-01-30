import { test, expect } from "@playwright/test";

test("live trade tables stay within card boundaries", async ({ page }) => {
  await page.goto("/live-trade");

  const staticTables = ["trade-runs-table", "trade-symbol-summary-table"];
  for (const id of staticTables) {
    const table = page.locator(`[data-testid="${id}"]`);
    await expect(table).toHaveCount(1);
    const wrapper = table.locator("xpath=ancestor::div[contains(@class,'table-scroll')][1]");
    await expect(wrapper).toHaveCount(1);
  }

  await page.getByTestId("trade-tab-orders").click();
  const ordersTable = page.locator('[data-testid="trade-orders-table"]');
  await expect(ordersTable).toHaveCount(1);
  await expect(
    ordersTable.locator("xpath=ancestor::div[contains(@class,'table-scroll')][1]")
  ).toHaveCount(1);

  await page.getByTestId("trade-tab-fills").click();
  const fillsTable = page.locator('[data-testid="trade-fills-table"]');
  await expect(fillsTable).toHaveCount(1);
  await expect(
    fillsTable.locator("xpath=ancestor::div[contains(@class,'table-scroll')][1]")
  ).toHaveCount(1);

  await page.getByTestId("trade-tab-receipts").click();
  const receiptsTable = page.locator('[data-testid="trade-receipts-table"]');
  await expect(receiptsTable).toHaveCount(1);
  await expect(
    receiptsTable.locator("xpath=ancestor::div[contains(@class,'table-scroll')][1]")
  ).toHaveCount(1);
});
