import { test, expect } from "@playwright/test";

test("live trade page shows connection state", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(
    page.locator(".meta-row span", { hasText: /连接状态|Connection status/i })
  ).toBeVisible();
});

test("live trade run table shows decision snapshot column", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByText(/决策快照|Decision Snapshot/i)).toBeVisible();
});

test("live trade page shows ib stream card", async ({ page }) => {
  await page.goto("/live-trade");
  const streamCard = page.locator(".card", {
    has: page.getByText(/IB 行情订阅|IB Stream/i),
  });
  await expect(streamCard).toBeVisible();
  await expect(
    streamCard.locator(".overview-label", { hasText: /行情类型|Market data type/i })
  ).toBeVisible();
  await expect(
    streamCard.locator(".meta-row span", { hasText: /最后错误|Last error/i })
  ).toBeVisible();
});
