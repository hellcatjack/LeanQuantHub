# 交易执行闭环与可视化增强 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 补齐订单状态/成交回写闭环，并新增“目标偏离对比 + 订单/成交明细”的可视化能力，覆盖 MKT+LMT。

**Architecture:** 在既有 `trade_runs/trade_orders/trade_fills` 上扩展：IB 回写事件→订单/成交表，新增 run detail 与 symbol 汇总接口；前端按批次展示偏离表与成交明细。

**Tech Stack:** FastAPI, SQLAlchemy, ibapi, React/Vite, Vitest, pytest

---

### Task 1: IB 回写事件采集（orderStatus + execDetails）

**Files:**
- Modify: `backend/app/services/ib_execution.py`
- Test: `backend/tests/test_ib_execution_events.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_ib_execution_events.py
from app.services.ib_execution import ExecutionEvent, IBExecutionClient


def test_submit_orders_collects_exec_events(monkeypatch):
    # 用假的 client 注入 orderStatus/execDetails 事件
    events = [
        ExecutionEvent(order_id=1, status="FILLED", exec_id="X1", filled=1, avg_price=10, ib_order_id=101),
        ExecutionEvent(order_id=2, status="REJECTED", exec_id=None, filled=0, avg_price=None, ib_order_id=102),
    ]

    monkeypatch.setattr(IBExecutionClient, "_submit_orders", lambda _self, _orders: events)
    client = IBExecutionClient("127.0.0.1", 4001, 1)
    result = client.submit_orders([object(), object()])
    assert [e.status for e in result] == ["FILLED", "REJECTED"]
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_ib_execution_events.py -q`
Expected: FAIL (missing test file or behavior not implemented)

**Step 3: Write minimal implementation**
- 在 `IBExecutionClient._submit_orders` 中增加对 execDetails/orderStatus 的收集（或注入 `_events` 队列）。
- 确保 `submit_orders` 返回真实事件列表。

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_ib_execution_events.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/ib_execution.py backend/tests/test_ib_execution_events.py
git commit -m "feat: collect ib execution events"
```

---

### Task 2: 成交回写去重（exec_id 幂等）

**Files:**
- Modify: `backend/app/services/ib_orders.py`
- Test: `backend/tests/test_trade_fills_dedupe.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_fills_dedupe.py
from app.services.ib_orders import apply_fill_to_order
from app.models import TradeOrder


def test_apply_fill_dedupes_exec_id(session):
    order = TradeOrder(client_order_id="x", symbol="SPY", side="BUY", quantity=1)
    session.add(order)
    session.commit()
    apply_fill_to_order(session, order, fill_qty=1, fill_price=10, exec_id="E1")
    apply_fill_to_order(session, order, fill_qty=1, fill_price=10, exec_id="E1")
    session.refresh(order)
    assert order.filled_quantity == 1
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_fills_dedupe.py -q`
Expected: FAIL (重复写入)

**Step 3: Write minimal implementation**
- `apply_fill_to_order` 内部先检查 `TradeFill.exec_id` 是否已存在（同 order_id + exec_id），存在则直接返回。

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_fills_dedupe.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/ib_orders.py backend/tests/test_trade_fills_dedupe.py
git commit -m "fix: dedupe fills by exec_id"
```

---

### Task 3: 执行时记录 portfolio_value（用于偏离计算）

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_run_portfolio_value.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_run_portfolio_value.py
from app.services.trade_executor import execute_trade_run


def test_trade_run_records_portfolio_value(monkeypatch, session, trade_run_with_orders):
    monkeypatch.setattr("app.services.trade_executor.fetch_account_summary", lambda *_a, **_k: {"NetLiquidation": 100000})
    execute_trade_run(trade_run_with_orders.id, dry_run=True)
    session.refresh(trade_run_with_orders)
    assert trade_run_with_orders.params.get("portfolio_value") == 100000
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_run_portfolio_value.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**
- 在 `execute_trade_run` 中取 `fetch_account_summary`，写入 `run.params["portfolio_value"]`。

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_run_portfolio_value.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_run_portfolio_value.py
git commit -m "feat: record portfolio value on trade run"
```

---

### Task 4: 交易批次详情与标的汇总接口

**Files:**
- Create: `backend/app/services/trade_run_summary.py`
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_run_summary.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_run_summary.py
from app.services.trade_run_summary import build_symbol_summary


def test_symbol_summary_aggregates(session, trade_run_with_orders_and_fills):
    summary = build_symbol_summary(session, trade_run_with_orders_and_fills.id)
    assert any(row["symbol"] == "SPY" for row in summary)
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_run_summary.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**
- 新增 `build_trade_run_detail`、`build_symbol_summary` 服务：聚合 fills、计算 `fill_ratio`、`delta_value/weight`。
- `trade.py` 增加 `GET /api/trade/runs/{run_id}/detail` 与 `/symbols` 路由。
- `schemas.py` 新增输出模型。

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_run_summary.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_run_summary.py backend/app/routes/trade.py backend/app/schemas.py backend/tests/test_trade_run_summary.py
git commit -m "feat: add trade run detail and symbol summary"
```

---

### Task 5: LMT 订单支持与校验

**Files:**
- Modify: `backend/app/services/ib_execution.py`
- Modify: `backend/app/services/trade_order_builder.py`
- Test: `backend/tests/test_trade_order_lmt.py`

**Step 1: Write the failing test**
```python
# backend/tests/test_trade_order_lmt.py
from app.services.trade_order_builder import build_orders


def test_build_orders_requires_limit_price_for_lmt():
    orders = build_orders([
        {"symbol": "SPY", "weight": 0.1}
    ], price_map={"SPY": 100}, portfolio_value=100000, order_type="LMT", limit_price=None)
    assert orders == []
```

**Step 2: Run test to verify it fails**
Run: `pytest backend/tests/test_trade_order_lmt.py -q`
Expected: FAIL

**Step 3: Write minimal implementation**
- `build_orders` 在 order_type=LMT 时要求 limit_price。
- `ib_execution.py` 下单时支持 LMT：`orderType="LMT"` + `lmtPrice`。

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_order_lmt.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_order_builder.py backend/app/services/ib_execution.py backend/tests/test_trade_order_lmt.py
git commit -m "feat: add lmt order support"
```

---

### Task 6: UI 增强（偏离对比 + 订单/成交明细）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/src/pages/LiveTradePage.test.ts`

**Step 1: Write the failing test**
```tsx
// frontend/src/pages/LiveTradePage.test.ts
it("renders symbol summary and fills table", () => {
  const html = ReactDOMServer.renderToString(React.createElement(LiveTradePage));
  expect(html).toContain("trade.symbolSummaryTitle");
  expect(html).toContain("trade.fillsTitle");
});
```

**Step 2: Run test to verify it fails**
Run: `cd frontend && npm test -- LiveTradePage.test.ts`
Expected: FAIL

**Step 3: Write minimal implementation**
- 新增 run_id 选择器，调用 `/runs/{id}/detail` 与 `/symbols`。
- 增加偏离表与订单/成交 Tab。
- i18n 增加中文文案。

**Step 4: Run test to verify it passes**
Run: `cd frontend && npm test -- LiveTradePage.test.ts`
Expected: PASS

**Step 5: Commit**
```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/src/pages/LiveTradePage.test.ts
git commit -m "ui: add trade run summary and fills view"
```

---

### Task 7: TODO 状态更新

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Update checklist**
- Phase 2: 订单状态机/成交回写/LMT 标记完成
- UI/UX：C+D 展示项标记完成

**Step 2: Commit**
```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: update IBAutoTradeTODO status"
```

---

**Plan complete and saved to `docs/plans/2026-01-24-trade-closure-visual-implementation-plan.md`. Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
