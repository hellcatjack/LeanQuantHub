import { test, expect } from "@playwright/test";

test("workflow selectors exist", async ({ page }) => {
  await page.goto("/data");
  await expect(page.getByTestId("pretrade-weekly-run")).toBeVisible();
  await expect(page.getByTestId("pretrade-weekly-status")).toBeVisible();

  await page.goto("/projects");
  await expect(page.getByTestId("project-item-16")).toBeVisible();
  await page.getByTestId("project-item-16").click();
  await expect(page.getByTestId("project-tab-algorithm")).toBeVisible();
  await page.getByTestId("project-tab-algorithm").click();
  await expect(page.getByTestId("decision-snapshot-run")).toBeVisible();

  await page.goto("/live-trade");
  await expect(page.getByTestId("live-trade-project-select")).toBeVisible();
  await expect(page.getByTestId("paper-trade-execute")).toBeVisible();
  await expect(page.getByTestId("paper-trade-status")).toBeVisible();
});
