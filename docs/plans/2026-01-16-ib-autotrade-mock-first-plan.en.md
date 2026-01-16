# IB AutoTrade Mock-First Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a runnable end-to-end trading loop (decision → risk → execution → monitoring) using Mock data while IB market data is unavailable, and keep the adapter boundary stable so real IB can be swapped in later.

**Architecture:** Use a unified `IBAdapter` interface and select `mock` or `ib` at runtime. Execution and risk checks read from adapter snapshots/history; the order state machine writes to DB; UI is read-only and can trigger mock runs.

**Tech Stack:** FastAPI, SQLAlchemy, React + Vite, pytest, Playwright.

---

## Strategy (Recommended)
- **Complete the Mock pipeline first** (order state machine, risk gates, fallback, monitoring, audit).
- **Keep adapter contracts stable**, then replace with real IB later.

---

## Task 1: Define IBAdapter boundaries + Mock data schema

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

## Task 2: Order idempotency + TradeOrder tests

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

## Task 3: Pre-trade risk gate (Mock-ready)

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

## Task 4: Decision snapshot binding + fallback

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

## Task 5: Live Trade UI minimal loop (Mock)

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
Expected: FAIL

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

## Task 6: Scheduler hook + run audit

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

## Acceptance
- Mock mode runs end-to-end: snapshot → risk gate → mock execution → UI monitor.
- Full auditability: trade_runs / trade_orders / trade_fills are traceable.
- Real IB connection can be plugged in by swapping adapter + execution layer.

