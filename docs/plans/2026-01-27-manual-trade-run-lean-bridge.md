# 手动交易走 Lean IB 执行器实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 手动买/卖/全仓清空创建 TradeRun，并通过 Lean IB 执行器发送订单，形成可追踪回写闭环。

**Architecture:** 新增“手动执行 Run”接口与 intent 写入逻辑；`trade_executor` 支持 `risk_bypass` 跳过风控；LeanBridgeExecutionAlgorithm 支持负数量（SELL）；前端触发改为调用新接口并展示 run_id。

**Tech Stack:** FastAPI + SQLAlchemy, React + Vite, Lean C#, Playwright, Pytest

### Task 1: 后端手动执行 Run API（测试先行）

**Files:**
- Create: `backend/tests/test_trade_manual_run.py`
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/services/trade_order_intent.py`
- Modify: `backend/app/services/trade_executor.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_manual_run.py
# 1) POST /api/trade/runs/manual 创建 TradeRun
# 2) TradeOrder 全部带 run_id
# 3) intent 文件存在且 SELL 为负数量
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_manual_run.py -q`
Expected: FAIL (endpoint/intent 不存在)

**Step 3: Write minimal implementation**

- 新增 `/api/trade/runs/manual`：
  - 创建 run（params.source=manual）
  - create_trade_order(..., run_id=run.id)
  - 写 intent：`order_intent_manual_run_{run_id}.json`
  - 设置 `params.order_intent_path` & `params.risk_bypass=true`
  - 调用 `execute_trade_run(run.id, dry_run=False, force=True)`
- `trade_order_intent.py` 增加 `write_order_intent_manual` 支持 quantity + order_intent_id
- `trade_executor`：当 `params.risk_bypass=true` 跳过 `evaluate_orders`

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_manual_run.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_trade_manual_run.py backend/app/routes/trade.py backend/app/services/trade_order_intent.py backend/app/services/trade_executor.py
git commit -m "feat: add manual trade run api via lean execution"
```

### Task 2: Lean 支持 SELL（负数量）

**Files:**
- Modify: `Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs`
- Test: `Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs`

**Step 1: Write the failing test**

```csharp
// 新增测试：intent 中 quantity = -2
// BuildRequests 生成 UseQuantity=true 的请求
// OnData 触发 MarketOrder(quantity=-2)
```

**Step 2: Run test to verify it fails**

Run: `dotnet test Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs`
Expected: FAIL

**Step 3: Write minimal implementation**

- BuildRequests：允许 quantity < 0（UseQuantity=true）
- OnData：MarketOrder 使用 quantity（可为负）

**Step 4: Run test to verify it passes**

Run: `dotnet test Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs`
Expected: PASS

**Step 5: Commit**

```bash
git add Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs
git commit -m "feat: support sell quantity in lean bridge execution"
```

### Task 3: 前端使用手动执行接口

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Test: `frontend/tests/live-trade-flow.spec.ts`

**Step 1: Write the failing test**

```ts
// Playwright：点击卖出或全仓清空
// 断言返回 run_id 并显示执行状态 running/submitted_lean
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx playwright test tests/live-trade-flow.spec.ts --reporter=line`
Expected: FAIL

**Step 3: Write minimal implementation**

- 前端改为调用 `/api/trade/runs/manual`，用 `orders` 数组提交
- 回写 `run_id` 到 UI（实盘监控可展示）

**Step 4: Run test to verify it passes**

Run: `cd frontend && npx playwright test tests/live-trade-flow.spec.ts --reporter=line`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade-flow.spec.ts
git commit -m "feat: submit manual trade run from live trade positions"
```

### Task 4: 端到端验证与部署

**Files:**
- None

**Step 1: Run focused verification**

Run:
- `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_manual_run.py -q`
- `dotnet test Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs`
- `cd frontend && npx playwright test tests/live-trade-flow.spec.ts --reporter=line`

Expected: PASS

**Step 2: Deploy frontend build**

Run: `cd frontend && npm run build` then `systemctl --user restart stocklean-frontend`

**Step 3: Commit any doc updates**

```bash
git status -sb
```

