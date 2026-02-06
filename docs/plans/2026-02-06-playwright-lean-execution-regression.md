# Lean 执行参数回归 Playwright 实测 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 使用 Playwright 在项目 18 上发起回测与实盘（Paper）交易，验证 Lean 执行参数链路改动不回归。

**Architecture:** 基于现有 UI 流程进行端到端验证：
- Live Trade 通过 UI 创建并执行 Paper 交易，必要时读取 TradeRun API 验证 `order_intent_path` 与 `execution_params_path`。
- Backtests Center 通过 UI 发起回测并确认新 Run 出现。
- 仅新增临时测试脚本（如需），不改业务代码。

**Tech Stack:** Playwright（@playwright/test）、React + Vite 前端、FastAPI 后端、Lean 执行器

---

### Task 1: Live Trade Paper Workflow 回归（项目 18）

**Files:**
- Modify: 无
- Create: （可选）`/tmp/playwright-live-trade-lean.spec.ts`
- Test: `frontend/tests/live-trade-workflow.spec.ts` 或临时脚本

**Step 1: 确认环境可用**
- 目标服务：`E2E_BASE_URL` 可访问（默认 `http://192.168.1.31:8081`）
- 项目 18 已存在，且能生成决策快照
- 若需要 Lean 路径：`/api/trade/settings` 的 `execution_data_source` 为 `lean`

**Step 2: 运行 Live Trade 流程**
Run:
```
cd frontend && PLAYWRIGHT_LIVE_TRADE=1 E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-workflow.spec.ts --reporter=line
```
Expected:
- 触发 Project 18 纸面交易（Paper）创建与执行
- 相关状态元素可见、无致命错误

**Step 3:（可选）验证 Lean 执行参数**
- 通过 `/api/trade/runs/{id}` 确认 `params.order_intent_path` 与 `params.execution_params_path` 非空
- `execution_params_path` 包含 `execution_params_run_{id}.json`

---

### Task 2: Backtest 发起回归（项目 18）

**Files:**
- Create: `/tmp/playwright-backtest-launch.spec.ts`
- Modify: 无
- Test: 临时脚本

**Step 1: 编写临时 Playwright 用例**
```ts
import { test, expect } from "@playwright/test";

test("project 18 backtest launch", async ({ page }) => {
  await page.goto("/backtests");
  const projectInput = page.getByPlaceholder(/Project ID|项目 ID/);
  await projectInput.fill("18");
  const runButton = page.getByRole("button", { name: /Run Backtest|运行回测/i });
  const [response] = await Promise.all([
    page.waitForResponse((resp) =>
      resp.url().includes("/api/backtests") &&
      resp.request().method() === "POST" &&
      resp.status() === 200
    ),
    runButton.click(),
  ]);
  const run = await response.json();
  const runId = run?.id ?? run?.run_id;
  expect(runId).toBeTruthy();
  await expect(
    page.locator(".id-chip-text", { hasText: new RegExp(`#${runId}\\b`) })
  ).toBeVisible({ timeout: 60_000 });
});
```

**Step 2: 运行临时用例**
Run:
```
cd frontend && E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test /tmp/playwright-backtest-launch.spec.ts --reporter=line
```
Expected:
- `/api/backtests` 返回 200，且返回 `id`
- 回测列表出现对应 `ID#<id>`

**Step 3: 清理（可选）**
- 删除 `/tmp/playwright-backtest-launch.spec.ts`（避免遗留临时脚本）

---

### Task 3: 汇总结果

**Files:**
- Modify: 无
- Create: 无

**Step 1: 记录 Playwright 输出与关键状态**
- Live Trade：Paper 交易是否成功执行、是否出现阻断原因
- Backtest：新 Run 是否成功创建并出现在列表

**Step 2: 输出结论**
- 通过/失败/阻断（注明原因）
- 若阻断（如 Lean Bridge 不可用），给出具体提示
