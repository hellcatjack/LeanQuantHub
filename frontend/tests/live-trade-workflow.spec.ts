import { test, expect, type Page } from "@playwright/test";

test.setTimeout(120_000);

const waitForOutcome = async (
  page: Page,
  successId: string,
  errorId: string,
  timeout = 60_000,
  allowErrors: string[] = []
) => {
  await Promise.race([
    page.getByTestId(successId).waitFor({ state: "visible", timeout }),
    page.getByTestId(errorId).waitFor({ state: "visible", timeout }),
  ]);
  if (await page.getByTestId(errorId).isVisible()) {
    const message = await page.getByTestId(errorId).innerText();
    if (!allowErrors.some((item) => message.includes(item))) {
      throw new Error(message || `${errorId} visible`);
    }
    return message;
  }
  return null;
};

test("live trade paper workflow", async ({ page }) => {
  await page.goto("/data");
  const pretradeProjectSelect = page.getByTestId("pretrade-project-select");
  await expect(pretradeProjectSelect.locator("option", { hasText: "#18" })).toHaveCount(1, {
    timeout: 60_000,
  });
  await pretradeProjectSelect.selectOption("18");
  await expect(pretradeProjectSelect).toHaveValue("18");
  const pretradeStatus = page.getByTestId("pretrade-weekly-status");
  const initialPretradeValue = (await pretradeStatus.getAttribute("data-status")) || "";
  if (!initialPretradeValue) {
    const runButton = page.getByTestId("pretrade-weekly-run");
    // When a run is already active the button can be disabled while status is still loading.
    if (await runButton.isEnabled()) {
      try {
        // Avoid hanging the whole test when UI state flips to disabled mid-click.
        await runButton.click({ timeout: 5_000 });
      } catch {
        // If the button became disabled (run already active), just continue and wait for status.
      }
    }
  }
  await expect(pretradeStatus).toHaveAttribute(
    "data-status",
    /success|failed|canceled|running/,
    {
      timeout: 90_000,
    }
  );
  const pretradeValue = (await pretradeStatus.getAttribute("data-status")) || "";
  if (pretradeValue === "failed" || pretradeValue === "canceled") {
    throw new Error(`pretrade status ${pretradeValue}`);
  }

  await page.goto("/projects");
  await page.getByTestId("project-item-18").click();
  await page.getByTestId("project-tab-algorithm").click();
  // Ensure a latest successful decision snapshot exists before starting live-trade runs.
  const snapshotToday = page.getByTestId("decision-snapshot-today");
  await expect(snapshotToday).toBeVisible({ timeout: 60_000 });
  await expect(snapshotToday).not.toHaveText("-", { timeout: 60_000 });

  await page.goto("/live-trade");
  await page.getByTestId("live-trade-project-select").selectOption("18");
  await page.locator("details.algo-advanced > summary").click();
  const createRunButton = page.getByTestId("paper-trade-create");
  const priorRunId = await page.getByTestId("paper-trade-run-id").inputValue();
  await expect(createRunButton).toBeVisible({ timeout: 10_000 });
  await createRunButton.click();
  const runIdInput = page.getByTestId("paper-trade-run-id");
  await expect(runIdInput).not.toHaveValue("", { timeout: 60_000 });
  if (priorRunId) {
    await expect(runIdInput).not.toHaveValue(priorRunId, { timeout: 60_000 });
  }
  const tradeStatus = page.getByTestId("paper-trade-status");
  await expect(tradeStatus).toHaveAttribute("data-status", /queued|blocked|failed|done|running/, {
    timeout: 60_000,
  });
  await page.getByTestId("paper-trade-execute").click();
  await waitForOutcome(page, "paper-trade-result", "paper-trade-error");
});
