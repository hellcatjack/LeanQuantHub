import { test, expect } from "@playwright/test";

test("positions table supports select + batch close", async ({ page }) => {
  await page.goto("/live-trade");
  await page.getByTestId("account-positions-card").scrollIntoViewIfNeeded();

  const firstRow = page.getByTestId("account-positions-table").locator("tbody tr").first();
  await firstRow.getByRole("checkbox").check();

  let dialogMessage = "";
  page.once("dialog", async (dialog) => {
    dialogMessage = dialog.message();
    await dialog.dismiss();
  });
  await page.getByTestId("positions-batch-close").click();
  expect(dialogMessage).toMatch(/批量平仓|Batch Close|Confirm batch close/);
});
