import { test, expect, type Page, type TestInfo } from "@playwright/test";

const shouldRun = process.env.PLAYWRIGHT_LIVE_TRADE === "1";

test("paper flow - attach artifacts helper", async ({ page }, testInfo) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1 and live env");

  const before = testInfo.attachments.length;
  await page.goto("/live-trade");
  await attachArtifacts("smoke", page, testInfo, ["log"]);
  expect(testInfo.attachments.length).toBeGreaterThan(before);
});

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

const attachArtifacts = async (
  label: string,
  page: Page,
  testInfo: TestInfo,
  consoleLines: string[]
) => {
  const prefix = `playwright-artifacts/${label}`;
  await testInfo.attach(`${prefix}/screenshot`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png",
  });
  await testInfo.attach(`${prefix}/html`, {
    body: await page.content(),
    contentType: "text/html",
  });
  await testInfo.attach(`${prefix}/console`, {
    body: consoleLines.join("\n"),
    contentType: "text/plain",
  });
};

test("paper flow for project 16", async ({ page }, testInfo) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1 and live env");

  const projectId = "16";
  const attachmentBaseline = testInfo.attachments.length;
  const consoleLines: string[] = [];
  page.on("console", (msg) => {
    consoleLines.push(`[${new Date().toISOString()}] ${msg.type()} ${msg.text()}`);
  });

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
        await attachArtifacts("pretrade-blocked", page, testInfo, consoleLines);
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
  if (pretradeBlocked) {
    expect(testInfo.attachments.length).toBeGreaterThan(attachmentBaseline);
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

  try {
    await expect
      .poll(async () => (await snapshotDate.textContent())?.trim() || "")
      .not.toBe("-");
  } catch (err) {
    await attachArtifacts("decision-empty", page, testInfo, consoleLines);
    throw err;
  }
  console.log("[flow] decision snapshot final", (await snapshotDate.textContent())?.trim());

  console.log("[flow] open live-trade page");
  await page.goto("/live-trade");
  await page.getByTestId("live-trade-project-select").selectOption(projectId);

  const tradeSnapshotStatus = page.getByTestId("live-trade-snapshot-status");
  try {
    await expect(tradeSnapshotStatus).toBeVisible();

    const tradeSnapshotDate = page.getByTestId("live-trade-snapshot-date");
    await expect(tradeSnapshotDate).not.toHaveText("-");
  } catch (err) {
    await attachArtifacts("snapshot-missing", page, testInfo, consoleLines);
    throw err;
  }

  const netLiq = page.getByTestId("account-summary-NetLiquidation-value");
  await expect(netLiq).toBeVisible();
  const netLiqValue = parseNumber(await netLiq.textContent());
  console.log("[flow] net liquidation", netLiqValue);
  try {
    expect(netLiqValue).toBeGreaterThanOrEqual(30000);
    expect(netLiqValue).toBeLessThanOrEqual(32000);
  } catch (err) {
    await attachArtifacts("account-mismatch", page, testInfo, consoleLines);
    throw err;
  }
});
