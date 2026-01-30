# Playwright 实盘持仓买卖自测 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 扩展 Playwright 用例，覆盖“当前持仓”表的买入与卖出操作。

**Architecture:** 在现有 `frontend/tests/live-trade-positions-actions.spec.ts` 中追加买入/卖出步骤，复用确认弹窗与提交结果的验证方式。

**Tech Stack:** Playwright, React, Vite。

---

### Task 1: 扩展 Playwright 用例（TDD）

**Files:**
- Modify: `frontend/tests/live-trade-positions-actions.spec.ts`

**Step 1: Write the failing test**

在现有测试中追加：
- 找到第一行持仓
- 触发“买入”按钮，确认弹窗
- 验证页面出现提交结果（如 “已提交”/`orders submitted`）
- 触发“卖出”按钮，确认弹窗
- 再次验证提交结果

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:e2e -- tests/live-trade-positions-actions.spec.ts`
Expected: FAIL (买入/卖出未断言或元素未定位)

**Step 3: Implement minimal test steps**

- 使用 `page.getByRole("button", { name: /买入|Buy/ })`
- 使用 `page.getByRole("button", { name: /卖出|Sell/ })`
- 监听 `dialog` 并 `accept()`
- 用 `expect(page.getByText(/已提交|orders submitted/))` 验证提交结果

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test:e2e -- tests/live-trade-positions-actions.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/tests/live-trade-positions-actions.spec.ts
git commit -m "test: add buy/sell coverage for live trade positions"
```

---

### Task 2: 验证

- 本地运行 e2e：`cd frontend && npm run test:e2e -- tests/live-trade-positions-actions.spec.ts`
- 预期：买入/卖出步骤均通过、页面出现提交提示

