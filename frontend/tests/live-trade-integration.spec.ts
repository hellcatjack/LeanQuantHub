import { test, expect } from "@playwright/test";

test("live trade page loads real positions and summary", async ({ page }) => {
  const [positionsRes, summaryRes] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.url().includes("/api/brokerage/account/positions") && res.status() === 200
    ),
    page.waitForResponse(
      (res) => res.url().includes("/api/brokerage/account/summary") && res.status() === 200
    ),
    page.goto("/live-trade"),
  ]);

  expect(positionsRes.ok()).toBeTruthy();
  expect(summaryRes.ok()).toBeTruthy();

  const positionsCard = page.locator(".card", {
    has: page.locator(".card-title", { hasText: /当前持仓|Positions/i }),
  });
  await expect(positionsCard).toBeVisible();
  const spansTwo = await positionsCard.evaluate((el) => el.classList.contains("span-2"));
  expect(spansTwo).toBeTruthy();

  const rows = positionsCard.locator("tbody tr");
  await expect(rows).not.toHaveCount(0);
  await expect(positionsCard.locator("td.empty-state")).toHaveCount(0);

  const updatedText = await positionsCard.locator(".meta-row strong").first().innerText();
  expect(updatedText.trim()).not.toMatch(/^(无|none)$/i);

  const summaryCard = page.locator(".card", {
    has: page.locator(".card-title", { hasText: /账户概览|Account Summary/i }),
  });
  await expect(summaryCard).toBeVisible();
  await expect(summaryCard.locator(".meta-row")).not.toHaveCount(0);
});
