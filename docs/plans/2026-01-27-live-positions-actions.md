# 实盘交易持仓动作 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在实盘交易页面的持仓表中新增买/卖/平仓、批量平仓与全仓清空能力，并确保 Lean IB Bridge 回写可追踪。

**Architecture:** 基于 `LiveTradePage` 扩展持仓表 UI 与动作栏，调用现有 `/api/trade/orders` 下单。订单使用全局唯一 `client_order_id`（tag）贯穿下单与回写。

**Tech Stack:** React + Vite + TypeScript，Vitest，Playwright，FastAPI（现有接口）。

---

### Task 1: 定义全局唯一订单 tag 生成器

**Files:**
- Create: `frontend/src/utils/orderTag.ts`
- Test: `frontend/src/utils/orderTag.test.ts`

**Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { buildOrderTag } from "./orderTag";

describe("buildOrderTag", () => {
  it("generates unique tag with trade_run_id and index", () => {
    const tag1 = buildOrderTag(25, 0, 1700000000000, 1234);
    const tag2 = buildOrderTag(25, 1, 1700000000000, 1234);
    expect(tag1).toContain("oi_25_0_");
    expect(tag2).toContain("oi_25_1_");
    expect(tag1).not.toBe(tag2);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- src/utils/orderTag.test.ts`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```ts
export function buildOrderTag(
  tradeRunId: number,
  index: number,
  epochMs: number = Date.now(),
  rand4: number = Math.floor(Math.random() * 10000)
) {
  const padded = String(rand4).padStart(4, "0");
  return `oi_${tradeRunId}_${index}_${epochMs}_${padded}`;
}
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- src/utils/orderTag.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/utils/orderTag.ts frontend/src/utils/orderTag.test.ts

git commit -m "feat: add unique order tag generator"
```

---

### Task 2: 扩展持仓表 UI（勾选 + 动作列 + 批量栏 + 二次确认）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify (if needed): `frontend/src/styles.css` or existing style file

**Step 1: Write the failing test (Playwright)**

```ts
import { test, expect } from "@playwright/test";

test("positions table supports select + batch close", async ({ page }) => {
  await page.goto("http://192.168.1.31:8081");
  await page.getByText("实盘交易").click();
  await page.getByText("当前持仓").scrollIntoViewIfNeeded();
  const firstRow = page.locator("table tbody tr").first();
  await firstRow.getByRole("checkbox").check();
  await page.getByRole("button", { name: "批量平仓" }).click();
  await expect(page.getByText("确认批量平仓")).toBeVisible();
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade-positions-actions.spec.ts`
Expected: FAIL (selectors/actions missing)

**Step 3: Implement UI changes**

- 在持仓表新增 checkbox 列与“操作”列按钮。
- 表头上方增加批量操作栏（显示勾选数量、批量平仓、全仓清空按钮）。
- 使用 `window.confirm` 实现二次确认（新 i18n 文案）。
- 统一危险按钮样式（如 `button-danger`，必要时补样式）。

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade-positions-actions.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/tests/live-trade-positions-actions.spec.ts frontend/src/styles.css

git commit -m "feat: add positions actions and batch controls"
```

---

### Task 3: 挂接下单与回写展示

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Write the failing test (Vitest)**

```ts
import { describe, it, expect } from "vitest";
import { buildOrderTag } from "../utils/orderTag";

describe("order payload", () => {
  it("uses client_order_id tag", () => {
    const tag = buildOrderTag(16, 0, 1700000000000, 1);
    expect(tag.startsWith("oi_16_0_1700000000000_"))
      .toBe(true);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- src/utils/orderTag.test.ts`
Expected: FAIL if tag not used in payload yet

**Step 3: Implement order creation**

- 新增 `handleBuy/sell/close`：使用 `/api/trade/orders`，传入 `client_order_id`、symbol、side、quantity、order_type`。
- 批量平仓：按勾选持仓生成多条订单，每条使用 `buildOrderTag(tradeRunId, index)`。
- 全仓清空：对全部持仓同上。
- 回写展示：订单列表中增加 `client_order_id`（若已有，优先显示），并在 fills 里关联展示。

**Step 4: Run tests**

Run: `cd frontend && npm test` (Vitest)
Expected: PASS

Run: `cd frontend && npx playwright test tests/live-trade-positions-actions.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx

git commit -m "feat: wire position actions to trade orders"
```

---

### Task 4: 校验回写与 UI 明确提示

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Test: `frontend/tests/live-trade-positions-actions.spec.ts`

**Step 1: Extend Playwright test**

- 验证点击平仓后，订单列表出现带 `oi_` 的 `client_order_id`。

**Step 2: Run Playwright test**

Run: `cd frontend && npx playwright test tests/live-trade-positions-actions.spec.ts`
Expected: PASS

**Step 3: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade-positions-actions.spec.ts

git commit -m "test: verify order tag shown after position actions"
```

---

### Task 5: 运行完整验证

**Step 1: Run unit tests**

Run: `cd frontend && npm test`
Expected: PASS

**Step 2: Run Playwright**

Run: `cd frontend && npx playwright test tests/live-trade-positions-actions.spec.ts`
Expected: PASS

**Step 3: Build & restart**

Run:

```bash
cd frontend && npm run build

systemctl --user restart stocklean-frontend
```

Expected: build success, service restart ok

---

## Notes
- Playwright 使用现有 `http://192.168.1.31:8081`，无需登录。
- 继续复用现有 “实盘交易” 页面结构与按钮样式。
- 所有新文案统一写入 `frontend/src/i18n.tsx`。
