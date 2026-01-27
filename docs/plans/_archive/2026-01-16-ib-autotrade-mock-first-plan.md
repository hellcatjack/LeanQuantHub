# IB AutoTrade Mock-First Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在无 IB 行情订阅/真实连接可用的前提下，完成“决策 → 风控 → 下单 → 监控”的可运行闭环（Mock 驱动），并确保未来接入 IB 真连接时可无缝替换。

**Architecture:** 以 `IBAdapter` 作为统一接口，运行期选择 `mock` 或 `ib`。交易执行与风控完全基于 adapter 读取的快照/历史数据，订单状态机与审计写入 DB，UI 只读展示结果并允许触发“模拟执行”。

**Tech Stack:** FastAPI, SQLAlchemy, React + Vite, pytest, Playwright.

---

## 实施策略（推荐）
- **先完成 Mock 流程闭环**（订单状态机、风控、回退、监控、审计）
- **保持 adapter 接口稳定**，后续直接替换为真实 IB 行情/下单实现

---

## Task 1: 明确 IBAdapter 行为边界与 Mock 数据落地结构

**Files:**
- Modify: `backend/app/services/ib_market.py`
- Modify: `backend/app/services/ib_settings.py`
- Test: `backend/tests/test_ib_market_mock.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_ib_market_mock.py

def test_mock_snapshot_has_required_fields():
    data = fetch_market_snapshots(session, symbols=["SPY"], store=False)
    assert data and "data" in data[0]
    assert "last" in data[0]["data"] or "close" in data[0]["data"]
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_ib_market_mock.py -v`
Expected: FAIL (missing file or undefined fields)

**Step 3: Write minimal implementation**
```python
# Ensure mock snapshot payload always includes last/close fields
# Enforce adapter returns uniform schema: {symbol, data, source}
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_ib_market_mock.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/ib_market.py backend/app/services/ib_settings.py backend/tests/test_ib_market_mock.py
git commit -m "test: add mock ib snapshot schema test"
```

---

## Task 2: 订单状态机幂等性 + TradeOrder 单测补齐

**Files:**
- Modify: `backend/app/services/trade_orders.py`
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_trade_orders.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_orders.py

def test_client_order_id_idempotent(session):
    payload = {"symbol":"SPY","side":"BUY","quantity":10,"client_order_id":"run-1-SPY"}
    first = create_trade_order(session, payload)
    second = create_trade_order(session, payload)
    assert first.order.id == second.order.id
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_orders.py -v`
Expected: FAIL (duplicate or exception)

**Step 3: Write minimal implementation**
```python
# Ensure create_trade_order returns existing order when client_order_id matches
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_orders.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_orders.py backend/app/routes/trade.py backend/tests/test_trade_orders.py
git commit -m "feat: enforce trade order idempotency"
```

---

## Task 3: 预交易风控（Mock 可执行）

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_risk_gate.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_risk_gate.py

def test_risk_gate_blocks_large_single_position(session):
    run = create_trade_run_with_large_single_position(session)
    result = execute_trade_run(run.id, dry_run=True)
    assert result.status in {"blocked", "failed"}
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_risk_gate.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# Add pre-trade risk checks (max position %, max notional)
# Store block reason in run.message
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_risk_gate.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_executor.py backend/app/schemas.py backend/tests/test_trade_risk_gate.py
git commit -m "feat: add pre-trade risk gate"
```

---

## Task 4: 决策快照绑定与回退逻辑

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_trade_snapshot_binding.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_snapshot_binding.py

def test_trade_run_persists_decision_snapshot(session):
    run = create_trade_run_with_snapshot(session)
    result = execute_trade_run(run.id, dry_run=True)
    assert result.run_id == run.id
    assert session.get(TradeRun, run.id).decision_snapshot_id is not None
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_snapshot_binding.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# Ensure decision_snapshot_id is mandatory for live execution
# Add fallback_to_snapshot_id when blocked
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_snapshot_binding.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_executor.py backend/app/models.py backend/tests/test_trade_snapshot_binding.py
git commit -m "feat: bind decision snapshot and fallback"
```

---

## Task 5: 实盘交易 UI 最小闭环（Mock）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/live-trade.spec.ts`

**Step 1: Write the failing test**
```ts
// frontend/tests/live-trade.spec.ts
import { test, expect } from "@playwright/test";

test("live trade page shows connection state", async ({ page }) => {
  await page.goto("/live-trade");
  await expect(page.getByText(/连接状态|Connection/i)).toBeVisible();
});
```

**Step 2: Run test to verify it fails**
Run: `cd frontend && npx playwright test frontend/tests/live-trade.spec.ts --project=chromium`
Expected: FAIL (missing text or selector)

**Step 3: Write minimal implementation**
```tsx
// Add a compact status header: connection state + last heartbeat
// Add trade run table with decision snapshot id & status
```

**Step 4: Run test to verify it passes**
Run: `cd frontend && npx playwright test frontend/tests/live-trade.spec.ts --project=chromium`
Expected: PASS

**Step 5: Commit**
```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/tests/live-trade.spec.ts
git commit -m "feat: live trade mock dashboard"
```

---

## Task 6: 调度器占位与运行审计

**Files:**
- Modify: `backend/app/services/pretrade_runner.py`
- Modify: `backend/app/routes/pretrade.py`
- Test: `backend/tests/test_trade_run_schedule.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_run_schedule.py

def test_pretrade_can_trigger_trade_run(session):
    run = trigger_pretrade_and_trade_run(session)
    assert run.status in {"queued", "blocked"}
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_run_schedule.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# Add hook to create trade_run from decision snapshot in pretrade
# Ensure idempotent: same window only one trade_run
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_run_schedule.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/pretrade_runner.py backend/app/routes/pretrade.py backend/tests/test_trade_run_schedule.py
git commit -m "feat: pretrade triggers trade run"
```

---

## 计划完成验收
- Mock 模式下可完整跑通：决策快照 → 风控 → 下单（mock）→ 状态机 → UI 监控。
- 有完整审计：trade_runs / trade_orders / trade_fills 可追溯。
- 未来接入真实 IB 只需替换 adapter 与订单执行层。

