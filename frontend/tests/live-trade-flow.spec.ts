import { test, expect } from "@playwright/test";

const shouldRun = process.env.PLAYWRIGHT_LIVE_TRADE === "1";

test("paper flow - account summary testids", async ({ page }) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1 and live env");

  await page.goto("/live-trade");

  const netLiq = page.getByTestId("account-summary-NetLiquidation-value");
  await expect(netLiq).toBeVisible();
});

const parseNumber = (raw: string | null) => {
  if (!raw) return NaN;
  const normalized = raw.replace(/[^\d.-]/g, "");
  return Number.parseFloat(normalized);
};

test("paper flow for project 16", async ({ page }) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1 and live env");

  const projectId = "16";

  console.log("[flow] open data page");
  await page.goto("/data");
  await page.getByTestId("pretrade-project-select").selectOption(projectId);

  const pretradeStatus = page.getByTestId("pretrade-weekly-status");
  const initialStatus = await pretradeStatus.getAttribute("data-status");
  console.log("[flow] pretrade status initial", initialStatus);
  let pretradeBlocked = false;
  if (!initialStatus) {
    await page.getByTestId("pretrade-weekly-run").click();
    const resultNotice = page.getByTestId("pretrade-weekly-result");
    const errorNotice = page.getByTestId("pretrade-weekly-error");
    const race = Promise.race([
      resultNotice.waitFor({ state: "visible", timeout: 60000 }).then(() => "result"),
      errorNotice.waitFor({ state: "visible", timeout: 60000 }).then(() => "error"),
    ]);
    const outcome = await race;
    if (outcome === "error") {
      const detail = (await errorNotice.textContent())?.trim();
      if (detail && (detail.includes("已有运行中的") || detail.includes("单实例"))) {
        pretradeBlocked = true;
        console.log("[flow] pretrade blocked", detail);
      } else {
        throw new Error(`pretrade run failed: ${detail || "unknown error"}`);
      }
    }
  }

  try {
    await expect
      .poll(async () => (await pretradeStatus.getAttribute("data-status")) || "")
      .not.toBe("");
  } catch (err) {
    if (!pretradeBlocked) {
      throw err;
    }
  }
  console.log("[flow] pretrade status final", await pretradeStatus.getAttribute("data-status"));

  console.log("[flow] open projects page");
  await page.goto("/projects");
  await page.getByTestId(`project-item-${projectId}`).click();
  await page.getByTestId("project-tab-algorithm").click();

  const snapshotDate = page.getByTestId("decision-snapshot-today");
  const snapshotText = (await snapshotDate.textContent())?.trim();
  console.log("[flow] decision snapshot initial", snapshotText);
  if (!snapshotText || snapshotText === "-") {
    await page.getByTestId("decision-snapshot-run").click();
  }

  await expect
    .poll(async () => (await snapshotDate.textContent())?.trim() || "")
    .not.toBe("-");
  console.log("[flow] decision snapshot final", (await snapshotDate.textContent())?.trim());

  console.log("[flow] open live-trade page");
  await page.goto("/live-trade");
  await page.getByTestId("live-trade-project-select").selectOption(projectId);

  const tradeSnapshotStatus = page.getByTestId("live-trade-snapshot-status");
  await expect(tradeSnapshotStatus).toBeVisible();

  const tradeSnapshotDate = page.getByTestId("live-trade-snapshot-date");
  await expect(tradeSnapshotDate).not.toHaveText("-");

  const netLiq = page.getByTestId("account-summary-NetLiquidation-value");
  await expect(netLiq).toBeVisible();
  const netLiqValue = parseNumber(await netLiq.textContent());
  console.log("[flow] net liquidation", netLiqValue);
  expect(netLiqValue).toBeGreaterThanOrEqual(30000);
  expect(netLiqValue).toBeLessThanOrEqual(32000);
});
