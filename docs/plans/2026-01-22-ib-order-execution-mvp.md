# IB 订单执行 MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 打通 IB 实盘/模拟盘的最小下单闭环（下单→回报→成交→写库），用于 Paper 交易验证。

**Architecture:** 在 `ib_market.IBRequestSession` 中加入订单回报事件采集与同步等待；`ib_orders` 新增 live 提交逻辑并映射 `TradeOrder/TradeFill`；`trade_executor` 依据 IB 模式选择 live/ mock 执行。

**Tech Stack:** FastAPI + SQLAlchemy + ibapi（IB Gateway/TWS） + pytest

---

### Task 1: 新增 IB 订单回报采集（IBRequestSession）

**Files:**
- Modify: `backend/app/services/ib_market.py`
- Test: `backend/tests/test_ib_order_session.py`

**Step 1: Write the failing test**

```python
def test_ib_request_session_order_events_collect():
    session = IBRequestSession("127.0.0.1", 7497, 1, timeout=0.1)
    # 直接调用事件回调，模拟订单回报
    session.orderStatus(1, "Submitted", 0, 10, 100.0, 0, 0, 0, "", 0.0)
    session.execDetails(1, None, type("Exec", (), {"shares": 10, "price": 100.0, "time": "20260122 09:31:00"}))
    session.commissionReport(type("Commission", (), {"commission": 1.5}))

    payload = session._order_events.get(1)
    assert payload["status"] == "Submitted"
    assert payload["filled"] == 10
    assert payload["avg_fill_price"] == 100.0
    assert payload["commission"] == 1.5
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_order_session.py -v`
Expected: FAIL with "AttributeError: 'IBRequestSession' object has no attribute '_order_events'"

**Step 3: Write minimal implementation**

```python
# in IBRequestSession.__init__
self._order_events = {}
self._order_done = {}

# add callbacks

def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice=0.0):
    payload = self._order_events.setdefault(orderId, {"fills": []})
    payload.update({
        "status": status,
        "filled": float(filled or 0),
        "remaining": float(remaining or 0),
        "avg_fill_price": float(avgFillPrice or 0),
    })
    if status in {"Filled", "Cancelled", "ApiCancelled", "Inactive", "Rejected"}:
        self._order_done.setdefault(orderId, threading.Event()).set()


def execDetails(self, reqId, contract, execution):
    order_id = getattr(execution, "orderId", reqId)
    payload = self._order_events.setdefault(order_id, {"fills": []})
    payload["fills"].append({
        "quantity": float(getattr(execution, "shares", 0)),
        "price": float(getattr(execution, "price", 0)),
        "time": getattr(execution, "time", None),
    })


def commissionReport(self, commissionReport):
    # 挂到最近一次执行的订单
    pass  # 简化：后续由 submit_orders_live 合并
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_order_session.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_market.py backend/tests/test_ib_order_session.py
git commit -m "test: add ib request session order events"
```

---

### Task 2: IB live 下单服务（submit_orders_live）

**Files:**
- Modify: `backend/app/services/ib_orders.py`
- Modify: `backend/app/services/ib_market.py`
- Test: `backend/tests/test_ib_orders_live.py`

**Step 1: Write the failing test**

```python
def test_submit_orders_live_maps_fills(db_session, monkeypatch):
    orders = [
        TradeOrder(client_order_id="run-1-AAPL", symbol="AAPL", side="BUY", quantity=10, order_type="MKT")
    ]
    db_session.add_all(orders)
    db_session.commit()

    class FakeAdapter:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def place_order(self, *args, **kwargs):
            return {
                "order_id": 99,
                "status": "Filled",
                "filled": 10,
                "avg_fill_price": 100.0,
                "fills": [{"quantity": 10, "price": 100.0, "time": "20260122 09:31:00"}],
                "commission": 1.0,
            }, None

    monkeypatch.setattr("app.services.ib_orders.ib_adapter", lambda *a, **k: FakeAdapter())

    result = submit_orders_live(db_session, orders, price_map={"AAPL": 100.0})
    assert result["status"] == "filled"
    row = db_session.get(TradeOrder, orders[0].id)
    assert row.status == "FILLED"
    assert row.filled_quantity == 10
    assert row.avg_fill_price == 100.0
    assert db_session.query(TradeFill).count() == 1
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_orders_live.py -v`
Expected: FAIL with "NameError: submit_orders_live not defined"

**Step 3: Write minimal implementation**

```python
# in ib_orders.py
from app.services.ib_market import ib_adapter


def submit_orders_live(session, orders, *, price_map):
    with ib_adapter(get_or_create_ib_settings(session)) as api:
        # 逐单调用 api.place_order
        # 将返回的 status/fills 映射回 TradeOrder/TradeFill
        # params 中记录 broker_order_id
```

- `ib_market.IBLiveAdapter` 新增 `place_order(contract, order, timeout)` 方法：
  - 通过 `IBRequestSession.placeOrder` 下单
  - 等待 `orderStatus` 或超时
  - 返回 `{order_id, status, filled, avg_fill_price, fills, commission}`

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_orders_live.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_orders.py backend/app/services/ib_market.py backend/tests/test_ib_orders_live.py
git commit -m "feat: add ib live order submission"
```

---

### Task 3: 交易执行器接入 live 下单

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_executor_ib_live.py`

**Step 1: Write the failing test**

```python
def test_trade_executor_prefers_live_orders(db_session, monkeypatch):
    monkeypatch.setattr("app.services.ib_orders.submit_orders_live", lambda *a, **k: {"status": "filled", "orders": []})
    result = _submit_ib_orders(db_session, [], price_map={})
    assert result["status"] == "filled"
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_executor_ib_live.py -v`
Expected: FAIL if code path still uses submit_orders_mock

**Step 3: Write minimal implementation**

```python
# in trade_executor._submit_ib_orders
if resolve_ib_api_mode(settings_row) == "ib":
    return submit_orders_live(...)
return submit_orders_mock(...)
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_executor_ib_live.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_executor_ib_live.py
git commit -m "feat: route trade executor to ib live orders"
```

---

### Task 4: 最小文档与审计补充

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`
- Modify: `docs/todolists/IBAutoTradeTODO.en.md`

**Step 1: Update TODO status**
- 标记 Phase 2 已完成项
- 追加“实盘下单MVP已完成，仍缺风险/告警/调度”说明

**Step 2: Commit**

```bash
git add docs/todolists/IBAutoTradeTODO.md docs/todolists/IBAutoTradeTODO.en.md
git commit -m "docs: update ib autotrade todo status"
```

---

## Test Plan (Overall)
- 单测：`/app/stocklean/.venv/bin/pytest backend/tests/test_ib_order_session.py -v`
- 单测：`/app/stocklean/.venv/bin/pytest backend/tests/test_ib_orders_live.py -v`
- 单测：`/app/stocklean/.venv/bin/pytest backend/tests/test_trade_executor_ib_live.py -v`
- 全量回归：`/app/stocklean/.venv/bin/pytest -q`

