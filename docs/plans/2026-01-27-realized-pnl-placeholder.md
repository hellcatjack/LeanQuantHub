# 实盘持仓已实现盈亏展示调整实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 当已实现盈亏未回传时显示“未回传”而非数值，避免与 IB 实际数据不一致。

**Architecture:** 仅调整前端表格单元格展示逻辑；不修改后端数据源或回填逻辑。新增一条 Playwright 断言用例，验证 null 的已实现盈亏显示为“未回传”。

**Tech Stack:** React + TypeScript, Playwright, i18n (frontend/src/i18n.tsx)

### Task 1: 新增失败用例（前端 E2E）

**Files:**
- Modify: `frontend/tests/live-trade.spec.ts`

**Step 1: Write the failing test**

```ts
// 新增一个 test，stub positions，realized_pnl = null
// 断言 realized 列显示“未回传”
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts --reporter=line`

Expected: FAIL (realized 列当前显示 “-”)

### Task 2: 最小实现展示逻辑

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Write minimal implementation**

```ts
const formatRealizedPnl = (value?: number | null) =>
  value === null || value === undefined ? t("trade.positionTable.realizedMissing") : formatNumber(value);
```

使用该方法替换 realized_pnl 单元格展示。

**Step 2: Add i18n keys**

中文：`未回传`
英文：`Not reported`

**Step 3: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts --reporter=line`

Expected: PASS

### Task 3: 验证与收尾

**Files:**
- None (verification only)

**Step 1: Run focused Playwright test**

Run: `cd frontend && npx playwright test tests/live-trade.spec.ts --reporter=line`

Expected: PASS

**Step 2: Commit**

```bash
git add frontend/tests/live-trade.spec.ts frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx docs/plans/2026-01-27-realized-pnl-placeholder.md
git commit -m "fix: mark missing realized pnl as not reported"
```
