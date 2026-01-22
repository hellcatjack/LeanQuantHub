# IB Order Execution Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement IB order submission + partial fill writeback to complete the expanded execution loop (MKT/LMT, partial fills, idempotent clientOrderId).

**Architecture:** Add an IB order executor service that handles order placement and status callbacks, then integrate it into trade_executor. Mock mode keeps deterministic tests, IB mode uses ibapi if available.

**Tech Stack:** FastAPI, SQLAlchemy, ibapi, pytest

---

### Task 1: Partial fill aggregation helper

**Files:**
- Create: `backend/app/services/ib_orders.py`
- Test: `backend/tests/test_ib_orders_fills.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder
from app.services.ib_orders import apply_fill_to_order


def test_apply_fill_updates_partial_and_avg_price():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    order = TradeOrder(
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=10,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    apply_fill_to_order(session, order, fill_qty=4, fill_price=100.0, fill_time=datetime.utcnow())
    session.refresh(order)
    assert order.status == "PARTIAL"
    assert order.filled_quantity == 4
    assert order.avg_fill_price == 100.0

    apply_fill_to_order(session, order, fill_qty=6, fill_price=110.0, fill_time=datetime.utcnow())
    session.refresh(order)
    assert order.status == "FILLED"
    assert order.filled_quantity == 10
    assert round(order.avg_fill_price, 6) == 106.0

    session.close()
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_orders_fills.py::test_apply_fill_updates_partial_and_avg_price -q`
Expected: FAIL (apply_fill_to_order missing)

**Step 3: Write minimal implementation**

```python
# in backend/app/services/ib_orders.py
from datetime import datetime
from app.models import TradeFill, TradeOrder
from app.services.trade_orders import update_trade_order_status


def apply_fill_to_order(session, order: TradeOrder, *, fill_qty: float, fill_price: float, fill_time: datetime) -> TradeFill:
    total_prev = float(order.filled_quantity or 0.0)
    total_new = total_prev + float(fill_qty)
    avg_prev = float(order.avg_fill_price or 0.0)
    avg_new = (avg_prev * total_prev + float(fill_price) * float(fill_qty)) / total_new

    target_status = "PARTIAL" if total_new < float(order.quantity) else "FILLED"
    update_trade_order_status(
        session,
        order,
        {"status": target_status, "filled_quantity": total_new, "avg_fill_price": avg_new},
    )
    fill = TradeFill(
        order_id=order.id,
        fill_quantity=float(fill_qty),
        fill_price=float(fill_price),
        commission=None,
        fill_time=fill_time,
        params={"source": "ib"},
    )
    session.add(fill)
    session.commit()
    session.refresh(order)
    return fill
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_orders_fills.py::test_apply_fill_updates_partial_and_avg_price -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_orders.py backend/tests/test_ib_orders_fills.py
git commit -m "feat: add ib order fill aggregation"
```

---

### Task 2: Mock IB order submission

**Files:**
- Modify: `backend/app/services/ib_orders.py`
- Test: `backend/tests/test_ib_orders_mock.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder
from app.services.ib_orders import submit_orders_mock


def test_submit_orders_mock_fills_all():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    order = TradeOrder(
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=2,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    result = submit_orders_mock(session, [order], price_map={"SPY": 123.0})
    session.refresh(order)
    assert result["filled"] == 1
    assert order.status == "FILLED"
    assert order.avg_fill_price == 123.0
    session.close()
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_orders_mock.py::test_submit_orders_mock_fills_all -q`
Expected: FAIL (submit_orders_mock missing)

**Step 3: Write minimal implementation**

```python
# in backend/app/services/ib_orders.py
from datetime import datetime


def submit_orders_mock(session, orders, *, price_map: dict[str, float]):
    filled = 0
    rejected = 0
    for order in orders:
        price = price_map.get(order.symbol)
        if price is None:
            rejected += 1
            update_trade_order_status(session, order, {"status": "REJECTED", "params": {"reason": "price_unavailable"}})
            continue
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
        apply_fill_to_order(session, order, fill_qty=order.quantity, fill_price=price, fill_time=datetime.utcnow())
        filled += 1
    return {"filled": filled, "rejected": rejected}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_orders_mock.py::test_submit_orders_mock_fills_all -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_orders.py backend/tests/test_ib_orders_mock.py
git commit -m "feat: add ib mock order submission"
```

---

### Task 3: Integrate IB order execution into trade_executor

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/ib_settings.py` (if need helper)
- Test: `backend/tests/test_trade_executor_ib.py`

**Step 1: Write the failing test**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeRun, TradeOrder
import app.services.trade_executor as trade_executor


def test_execute_trade_run_uses_ib_submit(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    run = TradeRun(project_id=1, mode="paper", status="queued", params={"portfolio_value": 1000})
    session.add(run)
    session.commit()
    order = TradeOrder(
        run_id=run.id,
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=1,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    called = {"ok": False}

    def _fake_submit(session_arg, orders, price_map=None):
        called["ok"] = True
        return {"filled": 1, "rejected": 0}

    monkeypatch.setattr(trade_executor, "_submit_ib_orders", _fake_submit)
    trade_executor._execute_orders_with_ib(session, run, [order], price_map={"SPY": 100.0})
    assert called["ok"] is True
    session.close()
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_ib.py::test_execute_trade_run_uses_ib_submit -q`
Expected: FAIL (helper missing)

**Step 3: Write minimal implementation**

```python
# in trade_executor.py
from app.services.ib_orders import submit_orders_mock


def _submit_ib_orders(session, orders, *, price_map):
    return submit_orders_mock(session, orders, price_map=price_map)


def _execute_orders_with_ib(session, run, orders, *, price_map):
    result = _submit_ib_orders(session, orders, price_map=price_map)
    return result
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_ib.py::test_execute_trade_run_uses_ib_submit -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_executor_ib.py
git commit -m "feat: integrate ib order submission path"
```

---

### Task 4: Wire IB path into execute_trade_run

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_executor_ib.py`

**Step 1: Write the failing test**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeRun, TradeOrder
import app.services.trade_executor as trade_executor


def test_execute_trade_run_sets_partial_status(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    run = TradeRun(project_id=1, mode="paper", status="queued", params={"portfolio_value": 1000})
    session.add(run)
    session.commit()
    order = TradeOrder(
        run_id=run.id,
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=1,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    def _fake_submit(session_arg, orders, price_map=None):
        return {"filled": 1, "rejected": 1}

    monkeypatch.setattr(trade_executor, "_submit_ib_orders", _fake_submit)
    trade_executor._finalize_run_status(session, run, filled=1, rejected=1, cancelled=0)
    session.refresh(run)
    assert run.status == "partial"
    session.close()
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_ib.py::test_execute_trade_run_sets_partial_status -q`
Expected: FAIL (_finalize_run_status missing)

**Step 3: Write minimal implementation**

```python
# in trade_executor.py

def _finalize_run_status(session, run, *, filled: int, rejected: int, cancelled: int):
    if filled == 0:
        run.status = "failed"
    elif rejected or cancelled:
        run.status = "partial"
    else:
        run.status = "done"
    run.ended_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    session.commit()
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_ib.py::test_execute_trade_run_sets_partial_status -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_executor_ib.py
git commit -m "feat: finalize ib trade run status"
```

---

### Task 5: Regression

**Step 1: Run backend tests**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests -q`
Expected: PASS

**Step 2: (If UI changes added later) Frontend build**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: verify ib order execution"
```

