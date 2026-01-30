# Live Trade 刷新整合设计与实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实盘交易页面仅保留一个“刷新全部”按钮；统一开关控制所有自动更新；每张卡清晰展示各自的刷新周期与下一次精准刷新时间。

**Architecture:** 前端新增统一刷新调度器（集中维护 interval/next/last/autoEnabled），替代当前分散的多处 `setInterval`；UI 通过调度器向各卡注入“周期/下次刷新/上次刷新/自动更新状态”。

**Tech Stack:** React + Vite + TypeScript、Playwright、现有 i18n 体系。

---

## 设计要点（确认版）

1) **交互统一**
- 页面仅保留一个“刷新全部”按钮，触发全量刷新（状态/桥接/行情健康/账户/持仓/监控/执行/快照等）。
- 增加一个全局自动更新开关（启停全部定时器）。

2) **节奏透明**
- 每张卡展示：`刷新间隔 / 下次刷新时间 / 上次刷新时间`。
- 自动更新关闭时：显示“已暂停”，并冻结 `nextRefreshAt`。

3) **状态解释**
- 仍显示 degraded/过期，但卡面同时展示下一次更新时间，避免误解为“停止更新”。

---

# Implementation Plan

### Task 1: 统一刷新调度器（前端）

**Files:**
- Create: `frontend/src/utils/liveTradeRefreshScheduler.ts`
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Test: `frontend/tests/live-trade.spec.ts`

**Step 1: Write the failing test**

```ts
// frontend/tests/live-trade.spec.ts
import { test, expect } from "@playwright/test";

test("live trade shows single refresh control and auto toggle", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByTestId("live-trade-refresh-all")).toBeVisible();
  await expect(page.getByTestId("live-trade-auto-toggle")).toBeVisible();
  await expect(page.locator("[data-testid^=card-refresh-next]")).toHaveCount(5);
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "single refresh" --reporter=line`
Expected: FAIL (test ids not found)

**Step 3: Write minimal implementation**

```ts
// frontend/src/utils/liveTradeRefreshScheduler.ts
export type RefreshKey = "connection" | "account" | "positions" | "monitor" | "snapshot" | "execution";
export const REFRESH_INTERVALS: Record<RefreshKey, number> = {
  connection: 10_000,
  account: 60_000,
  positions: 60_000,
  monitor: 15_000,
  snapshot: 10_000,
  execution: 20_000,
};
```

```tsx
// frontend/src/pages/LiveTradePage.tsx (核心思路)
// 1) autoEnabled 全局开关
// 2) 使用统一 scheduler 计算 nextRefreshAt / lastRefreshAt
// 3) “刷新全部”按钮触发所有 loadX 方法
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "single refresh" --reporter=line`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/utils/liveTradeRefreshScheduler.ts frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade.spec.ts
git commit -m "feat: unify live trade refresh controls"
```

---

### Task 2: 卡面展示周期 / 下次刷新 / 上次刷新

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/live-trade.spec.ts`

**Step 1: Write the failing test**

```ts
// frontend/tests/live-trade.spec.ts

test("live trade cards show refresh interval and next time", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByTestId("card-refresh-interval-connection")).toBeVisible();
  await expect(page.getByTestId("card-refresh-next-connection")).toBeVisible();
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "refresh interval" --reporter=line`
Expected: FAIL

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
// 在 card 标题区或 meta 区展示：
// interval / next / last
```

```ts
// i18n.tsx
trade.refreshInterval
trade.refreshNext
trade.refreshLast
trade.autoUpdateOn
trade.autoUpdateOff
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "refresh interval" --reporter=line`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/tests/live-trade.spec.ts
git commit -m "feat: show live trade refresh schedule"
```

---

### Task 3: 删除多余刷新按钮 + 自动更新总开关

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Test: `frontend/tests/live-trade.spec.ts`

**Step 1: Write the failing test**

```ts
// frontend/tests/live-trade.spec.ts

test("live trade has single refresh button", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByRole("button", { name: /刷新全部|Refresh All/i })).toHaveCount(1);
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "single refresh button" --reporter=line`
Expected: FAIL

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
// 删除“刷新状态 / 探测 / 局部刷新”按钮，保留“刷新全部”
// 新增 toggle：自动更新开 / 关
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "single refresh button" --reporter=line`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade.spec.ts
git commit -m "feat: consolidate live trade refresh actions"
```

---

### Task 4: 自动更新开关逻辑与停更提示

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Test: `frontend/tests/live-trade.spec.ts`

**Step 1: Write the failing test**

```ts
// frontend/tests/live-trade.spec.ts

test("auto refresh toggle pauses updates", async ({ page }) => {
  await page.goto("/live-trade");
  await page.getByTestId("live-trade-auto-toggle").click();
  await expect(page.getByTestId("auto-refresh-status")).toHaveText(/已暂停|Paused/i);
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "auto refresh toggle" --reporter=line`
Expected: FAIL

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
// autoEnabled=false => 清理定时器 + nextRefreshAt 显示“暂停”
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts -g "auto refresh toggle" --reporter=line`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade.spec.ts
git commit -m "feat: pause/resume live trade auto refresh"
```

---

### Task 5: 回归测试 + 构建

**Files:**
- Test: `frontend/tests/live-trade*.spec.ts`

**Step 1: Run full live-trade E2E**

Run: `cd frontend && npm run test:e2e -- --grep "live trade"`
Expected: PASS

**Step 2: Build**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 3: Commit**

```bash
git status -sb
```
Expected: clean

---

## 验收标准
- 页面只剩一个“刷新全部”按钮。
- 每张卡显示刷新间隔 + 下次更新 + 上次更新。
- 自动更新全局开关可控，停止后不再定时请求。
- degraded / stale 信息仍显示，但能看到下一次更新时间。

