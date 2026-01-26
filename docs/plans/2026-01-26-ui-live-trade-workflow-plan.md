# 实盘交易 UI 全流程（含 Playwright 验证）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan.

**Goal:** 用 Playwright 在 UI 上跑通“周度检查 → 当日模型决策 → Paper 实盘执行 → 结果复核”的完整 workflow。

**Architecture:** 在关键 UI 节点加入稳定选择器（data-testid），新增一个端到端 Playwright 脚本，串联四段 UI 流程并进行状态断言；必要时补充 UI 文案或状态可视化以便自动验证。

**Tech Stack:** React + Vite 前端、Playwright E2E、Vitest 单测。

---

### Task 1: 增加关键 UI 元素的稳定选择器

**Files:**
- Modify: `frontend/src/pages/DataPage.tsx`
- Modify: `frontend/src/pages/ProjectAlgorithmsPage.tsx`
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/components/*`（若按钮/状态组件在通用组件中）

**Step 1: 写失败的 Playwright 测试（仅定位节点）**

```ts
// tests/live-trade-workflow.spec.ts (临时版本，仅断言选择器存在)
test('workflow selectors exist', async ({ page }) => {
  await page.goto(process.env.E2E_BASE_URL || 'http://192.168.1.31:8081');
  await expect(page.getByTestId('pretrade-weekly-run')).toBeVisible();
  await expect(page.getByTestId('decision-snapshot-run')).toBeVisible();
  await expect(page.getByTestId('paper-trade-execute')).toBeVisible();
});
```

**Step 2: 运行测试，确认失败**

Run: `cd frontend && npx playwright test tests/live-trade-workflow.spec.ts`
Expected: FAIL with missing test ids

**Step 3: 最小实现（添加 data-testid）**

- 为周度检查按钮/状态标签添加：`data-testid="pretrade-weekly-run"` / `data-testid="pretrade-weekly-status"`
- 为当日模型决策按钮/今日快照标签添加：`data-testid="decision-snapshot-run"` / `data-testid="decision-snapshot-today"`
- 为 Paper 执行按钮/状态标签添加：`data-testid="paper-trade-execute"` / `data-testid="paper-trade-status"`

**Step 4: 运行测试，确认通过**

Run: `cd frontend && npx playwright test tests/live-trade-workflow.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages frontend/src/components tests/live-trade-workflow.spec.ts
git commit -m "feat(ui): add stable selectors for live trade workflow"
```

---

### Task 2: 完整 Playwright workflow 脚本

**Files:**
- Modify: `frontend/tests/live-trade-workflow.spec.ts`

**Step 1: 写失败测试（全流程但断言占位）**

```ts
import { test, expect } from '@playwright/test';

test('live trade paper workflow', async ({ page }) => {
  await page.goto(process.env.E2E_BASE_URL || 'http://192.168.1.31:8081');
  // 1) 数据页周度检查
  // 2) 项目页当日决策
  // 3) 实盘交易页执行
  // 4) 结果复核
  // TODO: 断言关键状态
  expect(true).toBe(false);
});
```

**Step 2: 运行测试，确认失败**

Run: `cd frontend && npx playwright test tests/live-trade-workflow.spec.ts`
Expected: FAIL

**Step 3: 最小实现（按 UI 流程补齐操作 + 断言）**

- 数据页：点击 `pretrade-weekly-run`，等待 `pretrade-weekly-status` 出现“完成/通过”
- 项目页算法：点击 `decision-snapshot-run`，等待 `decision-snapshot-today` 可见
- 实盘交易页：选择项目 16（下拉/列表），点击 `paper-trade-execute`
- 等待 `paper-trade-status` 进入 `queued|running|done|blocked` 之一
- 若 blocked，记录状态文本并 `expect` 失败（输出原因）

**Step 4: 运行测试，确认通过**

Run: `cd frontend && npx playwright test tests/live-trade-workflow.spec.ts`
Expected: PASS（如果 bridge 状态 ok）

**Step 5: Commit**

```bash
git add frontend/tests/live-trade-workflow.spec.ts
git commit -m "test(e2e): add live trade paper workflow"
```

---

### Task 3: Playwright 环境与脚本稳定性

**Files:**
- Modify: `frontend/playwright.config.ts`（如需 baseURL / timeout）

**Step 1: 写失败测试（验证 baseURL/timeout）**

```ts
// 不修改时可能超时/找不到 baseURL
```

**Step 2: 运行测试，确认失败（如需）**

Run: `cd frontend && npx playwright test tests/live-trade-workflow.spec.ts`
Expected: FAIL if baseURL/timeouts are missing

**Step 3: 最小实现**

- 设置 `use.baseURL = process.env.E2E_BASE_URL || 'http://192.168.1.31:8081'`
- 适度增加 `expect`/`action` timeout

**Step 4: 运行测试，确认通过**

Run: `cd frontend && npx playwright test tests/live-trade-workflow.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/playwright.config.ts
git commit -m "test(e2e): stabilize playwright config"
```

---

### Task 4: 更新文档与 TODO 状态

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: 写失败检查（查找 TODO 状态）**
- 确认相关条目存在且未完成

**Step 2: 最小实现**
- 标记“UI 工作流 + Playwright 自动验证”已完成/进行中

**Step 3: Commit**

```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: update IB auto trade todo for UI workflow"
```

---

### Task 5: 完整验证

**Step 1: 安装 Playwright 浏览器**
Run: `cd frontend && npx playwright install`

**Step 2: 运行 E2E**
Run: `cd frontend && npx playwright test tests/live-trade-workflow.spec.ts`
Expected: PASS（如 bridge ok）

**Step 3: 记录执行结果**
- 保存关键截图与输出（Playwright 默认产物）

**Step 4: Commit（如有需要）**

```bash
git status
git add -A
git commit -m "test: verify live trade workflow"
```

---

Plan complete and saved to `docs/plans/2026-01-26-ui-live-trade-workflow-plan.md`. Two execution options:

1. Subagent-Driven (this session)
2. Parallel Session (separate)

Which approach?
