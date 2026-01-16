# 交易执行层（A+C-1）实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不依赖 IB API 的情况下完成订单生成 + 风控 + 执行器抽象的闭环，并保留 Lean/IB 执行器切换点。

**Architecture:** 统一 TradeRun 主流程，新增 `ExecutionProvider` 抽象、`OrderBuilder` 与 `RiskEngine`。Mock 执行器复用现有执行逻辑；Lean 执行器仅预留接口。

**Tech Stack:** FastAPI + SQLAlchemy + pytest

---

### Task 1: OrderBuilder（订单生成器）

**Files:**
- Create: `backend/app/services/trade_order_builder.py`
- Test: `backend/tests/test_trade_order_builder.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_order_builder.py
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_order_builder import build_orders


def test_build_orders_rounding():
    items = [
        {"symbol": "AAA", "weight": 0.2},
        {"symbol": "BBB", "weight": 0.1},
    ]
    price_map = {"AAA": 50.0, "BBB": 33.0}
    orders = build_orders(
        items,
        price_map=price_map,
        portfolio_value=10000,
        cash_buffer_ratio=0.1,
        lot_size=1,
    )
    assert len(orders) == 2
    assert orders[0]["symbol"] == "AAA"
    assert orders[0]["quantity"] == 36  # 10000*0.9*0.2/50
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_order_builder.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing function.

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_order_builder.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class OrderDraft:
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None


def build_orders(
    items: list[dict[str, Any]],
    *,
    price_map: dict[str, float],
    portfolio_value: float,
    cash_buffer_ratio: float = 0.0,
    lot_size: int = 1,
    order_type: str = "MKT",
    limit_price: float | None = None,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    effective_value = portfolio_value * (1.0 - max(0.0, cash_buffer_ratio))
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        weight = item.get("weight")
        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            continue
        price = price_map.get(symbol)
        if price is None or price <= 0:
            continue
        side = "BUY" if weight_value >= 0 else "SELL"
        target = abs(weight_value) * effective_value
        raw_qty = target / price
        qty = int(raw_qty // max(1, lot_size)) * max(1, lot_size)
        if qty <= 0:
            continue
        orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": qty,
                "order_type": order_type,
                "limit_price": limit_price,
            }
        )
    return orders
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_order_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_order_builder.py backend/tests/test_trade_order_builder.py
git commit -m "feat: add order builder for trade runs"
```

---

### Task 2: RiskEngine（风控引擎）

**Files:**
- Create: `backend/app/services/trade_risk_engine.py`
- Test: `backend/tests/test_trade_risk_engine.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_risk_engine.py
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_risk_engine import evaluate_orders


def test_risk_blocks_large_order():
    orders = [
        {"symbol": "AAA", "side": "BUY", "quantity": 100, "price": 100.0},
    ]
    ok, blocked, reasons = evaluate_orders(
        orders,
        max_order_notional=5000,
        max_position_ratio=None,
        portfolio_value=10000,
    )
    assert ok is False
    assert blocked and blocked[0]["symbol"] == "AAA"
    assert "max_order_notional" in reasons[0]
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_risk_engine.py -v`
Expected: FAIL with missing module/function.

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_risk_engine.py
from __future__ import annotations
from typing import Any


def evaluate_orders(
    orders: list[dict[str, Any]],
    *,
    max_order_notional: float | None,
    max_position_ratio: float | None,
    portfolio_value: float | None,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    blocked = []
    reasons = []
    for order in orders:
        qty = float(order.get("quantity") or 0)
        price = float(order.get("price") or 0)
        notional = qty * price
        if max_order_notional is not None and notional > float(max_order_notional):
            blocked.append(order)
            reasons.append(f"max_order_notional:{order.get('symbol')}")
            continue
        if max_position_ratio is not None and portfolio_value:
            ratio = notional / float(portfolio_value)
            if ratio > float(max_position_ratio):
                blocked.append(order)
                reasons.append(f"max_position_ratio:{order.get('symbol')}")
                continue
    ok = len(blocked) == 0
    return ok, blocked, reasons
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_risk_engine.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_risk_engine.py backend/tests/test_trade_risk_engine.py
git commit -m "feat: add trade risk engine"
```

---

### Task 3: ExecutionProvider 抽象与 TradeRun 执行改造

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/decision_snapshot.py`
- Test: `backend/tests/test_trade_execution_builder.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_execution_builder.py
from pathlib import Path
import sys
import csv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeRun, DecisionSnapshot
import app.services.trade_executor as trade_executor


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def _write_items(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        writer.writerow({"symbol": "AAA", "weight": "0.2", "score": "1.0", "rank": "1"})
        writer.writerow({"symbol": "BBB", "weight": "0.1", "score": "0.9", "rank": "2"})


def test_execute_builds_orders_from_snapshot(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "fetch_market_snapshots", lambda *a, **k: [
        {"symbol": "AAA", "data": {"last": 50}},
        {"symbol": "BBB", "data": {"last": 25}},
    ])
    session = Session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path)
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(project_id=project.id, decision_snapshot_id=snapshot.id, status="queued", mode="paper", params={
            "portfolio_value": 10000,
        })
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True)
        assert result.status in {"done", "running", "blocked", "failed"}
        # 订单应被创建
        orders = session.query(trade_executor.TradeOrder).filter_by(run_id=run.id).all()
        assert len(orders) == 2
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_execution_builder.py -v`
Expected: FAIL (orders not created / missing integration)

**Step 3: Implement minimal changes**

- 在 `trade_executor.execute_trade_run` 中：
  - 当 `TradeRun` 无订单时，读取 `DecisionSnapshot.items_path`，调用 `build_orders` 生成订单。
  - 使用 `create_trade_order` 落库，确保 `client_order_id` 幂等。
  - 将生成用的价格映射/参数写入 `run.params` 方便审计。
- 引入 `trade_order_builder` 与 `trade_risk_engine`，在执行前先做风控阻断。

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_execution_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_execution_builder.py
git commit -m "feat: build trade orders from decision snapshot"
```

---

### Task 4: 回归与整理

**Files:**
- Test: `backend/tests/test_trade_orders.py`
- Test: `backend/tests/test_trade_risk_gate.py`

**Step 1: Run regression tests**

Run: `pytest backend/tests/test_trade_orders.py backend/tests/test_trade_risk_gate.py -v`
Expected: PASS

**Step 2: Commit (if any fixes needed)**

```bash
git add backend/app/services/trade_executor.py
# only if regressions require patch
git commit -m "fix: adjust trade execution after order builder"
```

---

## Rollout Notes
- 若前端需要展示 `portfolio_value` 或风控参数，后续再加 UI。
- 真实 IB 执行接入后，仅需替换 ExecutionProvider，不改变主流程。

