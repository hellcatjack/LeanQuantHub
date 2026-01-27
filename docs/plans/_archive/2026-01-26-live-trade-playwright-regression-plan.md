# 实盘交易（Paper）全流程 Playwright 回归 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为项目 16 的 PreTrade → 决策快照 → 实盘交易（Paper）建立可重复的 Playwright 回归流程，并断言账户金额处于 30k–32k 区间（避免回测 100k 误用）。

**Architecture:** 通过 Playwright 端到端脚本串联 Data/Projects/LiveTrade 页面操作，使用稳定的 data-testid 选择器读取关键 UI 状态。账户金额来自 Lean Bridge 的 `account_summary.json`，前端仅做展示与断言。

**Tech Stack:** React + Vite、Playwright、FastAPI（后端 API）、Lean Bridge 输出文件。

---

### Task 1: 为账户概览增加稳定 data-testid

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Test: `frontend/tests/live-trade-flow.spec.ts`

**Step 1: 写失败测试（RED）**

在 `frontend/tests/live-trade-flow.spec.ts` 新增测试用例，读取 `data-testid="account-summary-NetLiquidation-value"` 并断言金额范围。此时页面尚无对应 testid，应失败。

示例片段（在测试里）：
```ts
const netLiq = page.getByTestId('account-summary-NetLiquidation-value');
await expect(netLiq).toBeVisible();
```

**Step 2: 运行测试确认失败**

Run:
```bash
cd frontend
E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts -g "paper flow"
```
Expected: FAIL，提示找不到 `account-summary-NetLiquidation-value`。

**Step 3: 最小实现（GREEN）**

在 `LiveTradePage.tsx` 的账户概览卡片渲染处增加稳定 testid（不改现有文案）：
- 容器：`data-testid="account-summary-${item.key}"`
- 值：`data-testid="account-summary-${item.key}-value"`

**Step 4: 重新运行测试**

Run:
```bash
cd frontend
E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts -g "paper flow"
```
Expected: PASS。

**Step 5: 提交**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade-flow.spec.ts
git commit -m "test: add live trade paper flow selectors"
```

---

### Task 2: 编写项目 16 Paper 全流程 Playwright 脚本

**Files:**
- Create: `frontend/tests/live-trade-flow.spec.ts`

**Step 1: 写失败测试（RED）**

新增测试用例 `paper flow for project 16`，流程：
1) 访问 `/data`，选择项目 16 并触发 PreTrade 周度检查（若状态已完成则跳过）。
2) 访问 `/projects`，选择项目 16，确保“当日模型决策”可读取（必要时触发生成）。
3) 访问 `/live-trade`，选择项目 16，断言账户概览 NetLiquidation 在 30k–32k。**不执行实际下单**。

测试必须模拟真实用户点击，全部通过 UI 操作完成。

**Step 2: 运行测试确认失败**

同 Task 1 的命令。预期失败点可能为 selector 不稳定或断言失败。

**Step 3: 最小实现（GREEN）**

若发现缺少稳定选择器，则在相关页面补充 data-testid（只在必要处）：
- Data 页面 PreTrade 选择与运行按钮
- Projects 页面决策快照按钮与状态
- Live Trade 页面项目选择与快照状态

（已有 testid 就不改）

**Step 4: 重新运行测试**

Run:
```bash
cd frontend
E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts -g "paper flow"
```
Expected: PASS。

**Step 5: 提交**

```bash
git add frontend/tests/live-trade-flow.spec.ts frontend/src/pages/*.tsx
git commit -m "test: add project 16 paper flow e2e"
```

---

### Task 3: 生产构建与服务重启（前端变更必做）

**Files:**
- Modify: `frontend/` 构建产物

**Step 1: 构建前端**

```bash
cd frontend
npm run build
```
Expected: build 成功，无 error。

**Step 2: 重启前端服务**

```bash
systemctl --user restart stocklean-frontend
```

**Step 3: 最终回归**

```bash
cd frontend
E2E_BASE_URL="http://192.168.1.31:8081" npx playwright test tests/live-trade-flow.spec.ts -g "paper flow"
```
Expected: PASS。

**Step 4: 提交**

```bash
git add -A
git commit -m "chore: rebuild frontend after live trade e2e"
```

---

## 运行前提/约束
- Playwright 走 UI，不使用直连 API。
- 不执行真实下单，仅验证页面与账户金额。
- 账户金额断言为 30000–32000（Paper 账户），避免误用回测 100000。
- `E2E_BASE_URL` 使用 `http://192.168.1.31:8081`，页面无登录。
- Python 使用 `/app/stocklean/.venv`，后端配置读取 `backend/.env`。

