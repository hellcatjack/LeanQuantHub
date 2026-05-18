import { test, expect } from "@playwright/test";

test("live trade shows paper covered call audit panel as read-only", async ({ page }) => {
  await page.route("**/api/trade/options/covered-call/audit/recent", async (route) => {
    const body = route.request().postDataJSON() as {
      query?: string;
      offset?: number;
      limit?: number;
    };
    const query = String(body?.query || "").toLowerCase();
    const offset = Number(body?.offset || 0);
    const limit = Number(body?.limit || 10);
    let items = [
      {
        review_id: "review-alpha",
        created_at: "2026-04-08T12:00:00Z",
        symbol: "AAPL",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: null,
      },
      {
        review_id: "review-delta",
        created_at: "2026-04-08T11:45:00Z",
        symbol: "NVDA",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: null,
      },
      {
        review_id: "review-epsilon",
        created_at: "2026-04-08T11:40:00Z",
        symbol: "META",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: null,
      },
      {
        review_id: "review-zeta",
        created_at: "2026-04-08T11:35:00Z",
        symbol: "TSLA",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: null,
      },
      {
        review_id: "review-eta",
        created_at: "2026-04-08T11:30:00Z",
        symbol: "AVGO",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: null,
      },
      {
        review_id: "review-theta",
        created_at: "2026-04-08T11:25:00Z",
        symbol: "CRM",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: null,
      },
      {
        review_id: "review-iota",
        created_at: "2026-04-08T11:20:00Z",
        symbol: "INTU",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: null,
      },
      {
        review_id: "review-gamma",
        created_at: "2026-04-08T10:00:00Z",
        symbol: "AMD",
        status: "ready",
        timeline_state: "awaiting_submit",
        latest_command_id: "cmd-3",
      },
      {
        review_id: "review-beta",
        created_at: "2026-04-08T11:00:00Z",
        symbol: "MSFT",
        status: "blocked",
        timeline_state: "submit_blocked",
        latest_command_id: null,
      },
    ];
    if (query) {
      items = items.filter((item) =>
        [item.review_id, item.symbol, item.status, item.timeline_state]
          .join(" ")
          .toLowerCase()
          .includes(query),
      );
    }
    const total = items.length;
    const paged = items.slice(offset, offset + limit);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        mode: "paper",
        total,
        has_more: offset + paged.length < total,
        items: paged,
      }),
    });
  });

  await page.route("**/api/trade/options/covered-call/audit", async (route) => {
    const request = route.request();
    const body = request.postDataJSON() as { review_id?: string };
    const reviewId = body?.review_id || "review-alpha";
    const payload =
      reviewId === "review-beta"
        ? {
            mode: "paper",
            status: "blocked",
            timeline_state: "submit_blocked",
            review_id: "review-beta",
            review: { status: "ready" },
            submit: { status: "blocked" },
            receipt: null,
            timeline: {
              status: "blocked",
              timeline_state: "submit_blocked",
              review_id: "review-beta",
              latest_submit: { command_id: null },
              latest_receipt: null,
              stages: [{ label: "submit", status: "blocked", at: "2026-04-08T12:01:00Z" }],
              artifacts: { summary: "/tmp/review-beta.json" },
            },
            artifacts: {
              summary: "/tmp/review-beta.json",
              review_bundle: "/tmp/review-beta-bundle.json",
              timeline_summary: "/tmp/review-beta-timeline.json",
              latest_submit_summary: null,
              latest_receipt_summary: null,
            },
          }
        : {
            mode: "paper",
            status: "ready",
            timeline_state: "awaiting_submit",
            review_id: "review-alpha",
            review: { status: "ready" },
            submit: null,
            receipt: null,
            timeline: {
              status: "ready",
              timeline_state: "awaiting_submit",
              review_id: "review-alpha",
              latest_submit: null,
              latest_receipt: null,
              stages: [{ label: "review", status: "ready", at: "2026-04-08T12:00:00Z" }],
              artifacts: { summary: "/tmp/review-alpha.json" },
            },
            artifacts: {
              summary: "/tmp/review-alpha.json",
              review_bundle: "/tmp/review-alpha-bundle.json",
              timeline_summary: "/tmp/review-alpha-timeline.json",
              latest_submit_summary: null,
              latest_receipt_summary: null,
            },
          };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });

  await page.goto("/live-trade");

  const panel = page.getByTestId("covered-call-audit-panel");
  await expect(panel).toBeVisible({ timeout: 30000 });
  await expect(panel).toContainText("Covered Call Pilot");
  await expect(panel).toContainText("Paper Only");
  await expect(panel).toContainText("review-alpha");
  await expect(panel).toContainText("AAPL");
  await expect(panel).toContainText("2026-04-08T12:00:00Z");
  await expect(panel).toContainText("awaiting_submit");
  await expect(panel).toContainText("Artifacts");
  await expect(panel).toContainText("1-8 / 9");
  await expect(
    page.getByRole("button", { name: /^submit$/i }),
  ).toHaveCount(0);

  await page.getByPlaceholder("Search reviews").fill("amd");
  await expect(panel).toContainText("review-gamma");
  await expect(panel).toContainText("1-1 / 1");

  await page.getByPlaceholder("Search reviews").fill("");
  const panelNextButton = panel.getByRole("button", { name: "Next" });
  await expect(panel).toContainText("1-8 / 9");
  await expect(panelNextButton).toBeEnabled();
  await panelNextButton.click();
  await expect(panel).toContainText("review-beta");
  await expect(panel).toContainText("9-9 / 9");

  await page.getByRole("button", { name: /review-beta/i }).click();
  await expect(panel).toContainText("review-beta");
  await expect(panel).toContainText("submit_blocked");
  await expect(panel).toContainText("/tmp/review-beta.json");
  await expect(panel).toContainText("review-beta-bundle.json");
});
