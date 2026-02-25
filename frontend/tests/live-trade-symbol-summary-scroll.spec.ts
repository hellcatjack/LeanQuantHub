import { expect, test } from "@playwright/test";

test("symbol summary expands fully without inner scroll bar and exposes total count", async ({
  page,
}) => {
  await page.goto("/live-trade");

  const table = page.getByTestId("trade-symbol-summary-table");
  await expect(table).toHaveCount(1);

  const wrapper = page.getByTestId("trade-symbol-summary-scroll");
  await expect(wrapper).toHaveCount(1);

  const overflow = await wrapper.evaluate((el) => {
    const style = window.getComputedStyle(el);
    return { overflowX: style.overflowX, overflowY: style.overflowY, maxHeight: style.maxHeight };
  });
  expect(overflow.maxHeight).toBe("none");
  expect(["visible", "clip"]).toContain(overflow.overflowX);
  expect(["visible", "clip"]).toContain(overflow.overflowY);

  const countText = await page.getByTestId("trade-symbol-summary-count").textContent();
  expect(Number.isFinite(Number((countText || "").trim()))).toBe(true);

  const rowStats = await wrapper.evaluate((el) => {
    const rows = el.querySelectorAll("tbody tr");
    return {
      rowCount: rows.length,
      clientHeight: el.clientHeight,
      scrollHeight: el.scrollHeight,
      scrollTop: el.scrollTop,
    };
  });
  expect(rowStats.rowCount).toBeGreaterThanOrEqual(1);
  expect(rowStats.scrollTop).toBe(0);
  expect(rowStats.scrollHeight).toBeGreaterThanOrEqual(rowStats.clientHeight);
});
