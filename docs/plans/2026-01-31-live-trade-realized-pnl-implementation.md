# 实盘交易已实现盈亏（FIFO）实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan.

**Goal:** 基于首次持仓快照 + TradeFill FIFO 计算已实现盈亏，并在持仓/成交/回执/订单明细中展示。

**Architecture:** 在后端新增 realized_pnl 计算服务：加载持仓基准快照（positions_baseline.json），用 TradeFill + TradeOrder 逐笔 FIFO 计算每标的/每成交/每订单 realized_pnl。持仓接口聚合展示，成交/回执/订单明细显示可核对字段。

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + Vite (frontend), pytest, Playwright (验证)

---

### Task 1: 新增 FIFO 已实现盈亏计算服务（后端）

**Files:**
- Create: `backend/app/services/realized_pnl.py`
- Modify: `backend/app/services/lean_bridge_paths.py` (如需新增路径工具)
- Test: `backend/tests/test_realized_pnl_fifo.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_realized_pnl_fifo.py
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder, TradeFill
from app.services.realized_pnl import compute_realized_pnl


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_fifo_realized_pnl_with_commission():
    session = _make_session()
    try:
        # baseline: long 10 @100
        baseline = {
            "created_at": "2026-01-30T00:00:00Z",
            "items": [{"symbol": "AAPL", "position": 10, "avg_cost": 100.0}],
        }

        # sell 6 @110, commission 1.2
        order = TradeOrder(
            run_id=None,
            client_order_id="oi_0_0_1",
            symbol="AAPL",
            side="SELL",
            quantity=6,
            order_type="MKT",
            status="FILLED",
            filled_quantity=6,
            avg_fill_price=110.0,
        )
        session.add(order)
        session.flush()
        fill = TradeFill(
            order_id=order.id,
            fill_quantity=6,
            fill_price=110.0,
            commission=1.2,
            fill_time=datetime(2026, 1, 30, 0, 1, tzinfo=timezone.utc),
        )
        session.add(fill)
        session.commit()

        result = compute_realized_pnl(session, baseline)
        assert round(result.symbol_totals["AAPL"], 6) == round((110 - 100) * 6 - 1.2, 6)
        assert round(result.fill_totals[fill.id], 6) == round((110 - 100) * 6 - 1.2, 6)
        assert round(result.order_totals[order.id], 6) == round((110 - 100) * 6 - 1.2, 6)
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_realized_pnl_fifo.py::test_fifo_realized_pnl_with_commission -v`
Expected: FAIL (compute_realized_pnl not found)

**Step 3: Write minimal implementation**

```python
# backend/app/services/realized_pnl.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

from app.models import TradeFill, TradeOrder
from app.services.lean_bridge_paths import resolve_bridge_root


@dataclass
class RealizedPnlResult:
    symbol_totals: dict[str, float]
    order_totals: dict[int, float]
    fill_totals: dict[int, float]
    baseline_at: datetime | None


@dataclass
class Lot:
    qty: float
    cost: float


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_realized_pnl(session, baseline: dict) -> RealizedPnlResult:
    baseline_at = _parse_time(str(baseline.get("created_at") or ""))
    symbol_totals: dict[str, float] = {}
    order_totals: dict[int, float] = {}
    fill_totals: dict[int, float] = {}
    lots: dict[str, list[Lot]] = {}

    # seed lots
    for item in baseline.get("items") or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        qty = float(item.get("position") or 0.0)
        if qty == 0:
            continue
        cost = float(item.get("avg_cost") or 0.0)
        lots.setdefault(symbol, []).append(Lot(qty=qty, cost=cost))
        symbol_totals.setdefault(symbol, 0.0)

    rows = (
        session.query(TradeFill, TradeOrder)
        .join(TradeOrder, TradeFill.order_id == TradeOrder.id)
        .all()
    )

    def effective_time(fill: TradeFill) -> datetime | None:
        return fill.fill_time or fill.created_at

    rows = sorted(rows, key=lambda r: (effective_time(r[0]) or datetime.min))

    for fill, order in rows:
        symbol = (order.symbol or "").strip().upper()
        if not symbol:
            continue
        dt = effective_time(fill)
        if baseline_at and dt and dt < baseline_at:
            continue
        side = (order.side or "").strip().upper()
        qty = abs(float(fill.fill_quantity or 0.0))
        if qty <= 0:
            continue
        price = float(fill.fill_price or 0.0)
        commission = float(fill.commission or 0.0)
        commission_per_share = commission / qty if qty else 0.0

        symbol_totals.setdefault(symbol, 0.0)
        order_totals.setdefault(order.id, 0.0)

        def realize(amount: float, matched_qty: float):
            symbol_totals[symbol] += amount
            order_totals[order.id] += amount
            fill_totals[fill.id] = fill_totals.get(fill.id, 0.0) + amount

        fifo = lots.setdefault(symbol, [])
        remaining = qty

        if side == "BUY":
            # cover shorts first
            while remaining > 0 and fifo and fifo[0].qty < 0:
                lot = fifo[0]
                match_qty = min(remaining, abs(lot.qty))
                realized = (lot.cost - price) * match_qty - commission_per_share * match_qty
                realize(realized, match_qty)
                lot.qty += match_qty  # lot.qty is negative
                remaining -= match_qty
                if abs(lot.qty) < 1e-9:
                    fifo.pop(0)
            if remaining > 0:
                open_cost = price + commission_per_share
                fifo.append(Lot(qty=remaining, cost=open_cost))
        elif side == "SELL":
            while remaining > 0 and fifo and fifo[0].qty > 0:
                lot = fifo[0]
                match_qty = min(remaining, lot.qty)
                realized = (price - lot.cost) * match_qty - commission_per_share * match_qty
                realize(realized, match_qty)
                lot.qty -= match_qty
                remaining -= match_qty
                if lot.qty <= 1e-9:
                    fifo.pop(0)
            if remaining > 0:
                open_cost = price - commission_per_share
                fifo.append(Lot(qty=-remaining, cost=open_cost))
        else:
            continue

    return RealizedPnlResult(
        symbol_totals=symbol_totals,
        order_totals=order_totals,
        fill_totals=fill_totals,
        baseline_at=baseline_at,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_realized_pnl_fifo.py::test_fifo_realized_pnl_with_commission -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/realized_pnl.py backend/tests/test_realized_pnl_fifo.py

git commit -m "feat: add fifo realized pnl calculator"
```

---

### Task 2: 持仓接口接入已实现盈亏 + 基准快照

**Files:**
- Modify: `backend/app/services/ib_account.py`
- Create: `backend/app/services/realized_pnl_baseline.py`
- Test: `backend/tests/test_realized_pnl_baseline.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_realized_pnl_baseline.py
from datetime import datetime, timezone
from pathlib import Path

from app.services.realized_pnl_baseline import ensure_positions_baseline


def test_baseline_created_from_positions(tmp_path):
    root = tmp_path / "lean_bridge"
    root.mkdir(parents=True)
    payload = {
        "source_detail": "ib_holdings",
        "stale": False,
        "updated_at": "2026-01-30T00:00:00Z",
        "items": [{"symbol": "AAPL", "position": 10, "avg_cost": 100.0}],
    }
    baseline = ensure_positions_baseline(root, payload)
    assert baseline["items"][0]["symbol"] == "AAPL"
    assert (root / "positions_baseline.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_realized_pnl_baseline.py::test_baseline_created_from_positions -v`
Expected: FAIL (module/function missing)

**Step 3: Write minimal implementation**

```python
# backend/app/services/realized_pnl_baseline.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _baseline_path(root: Path) -> Path:
    return root / "positions_baseline.json"


def _parse_time(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value)
    return text


def ensure_positions_baseline(root: Path, payload: dict) -> dict:
    path = _baseline_path(root)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    source_detail = payload.get("source_detail")
    stale = bool(payload.get("stale", True))
    if source_detail != "ib_holdings" or stale:
        return {"created_at": None, "items": []}

    items = []
    for item in payload.get("items") or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        position = float(item.get("position") or 0.0)
        if position == 0:
            continue
        avg_cost = float(item.get("avg_cost") or item.get("avgCost") or 0.0)
        items.append({"symbol": symbol, "position": position, "avg_cost": avg_cost})

    baseline = {
        "created_at": _parse_time(payload.get("updated_at") or payload.get("refreshed_at")),
        "items": items,
    }
    path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_realized_pnl_baseline.py::test_baseline_created_from_positions -v`
Expected: PASS

**Step 5: Wire into positions**

```python
# backend/app/services/ib_account.py (snippet)
from app.services.realized_pnl_baseline import ensure_positions_baseline
from app.services.realized_pnl import compute_realized_pnl

# ... inside get_account_positions after items built
baseline = ensure_positions_baseline(_resolve_bridge_root(), payload)
realized = compute_realized_pnl(session, baseline)
for row in items:
    symbol = str(row.get("symbol") or "").strip().upper()
    row["realized_pnl"] = realized.symbol_totals.get(symbol, 0.0)
```

**Step 6: Run test for positions**

Run: `pytest backend/tests/test_ib_account_positions.py::test_ib_account_positions_rejects_non_ib_holdings -v`
Expected: PASS

**Step 7: Commit**

```bash
git add backend/app/services/realized_pnl_baseline.py backend/app/services/ib_account.py backend/tests/test_realized_pnl_baseline.py

git commit -m "feat: add positions baseline for realized pnl"
```

---

### Task 3: Trade detail/receipts/order 接口补齐 realized/commission/symbol/side

**Files:**
- Modify: `backend/app/services/trade_run_summary.py`
- Modify: `backend/app/services/trade_receipts.py`
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_detail_realized_pnl.py`

**Step 1: Write failing test**

```python
# backend/tests/test_trade_detail_realized_pnl.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder, TradeFill
from app.services.realized_pnl import compute_realized_pnl


def test_fill_detail_contains_realized_fields():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        order = TradeOrder(
            run_id=1,
            client_order_id="oi_0_0_1",
            symbol="AAPL",
            side="SELL",
            quantity=1,
            order_type="MKT",
            status="FILLED",
            filled_quantity=1,
            avg_fill_price=110.0,
        )
        session.add(order)
        session.flush()
        fill = TradeFill(order_id=order.id, fill_quantity=1, fill_price=110.0)
        session.add(fill)
        session.commit()

        baseline = {"created_at": "2026-01-30T00:00:00Z", "items": [{"symbol": "AAPL", "position": 1, "avg_cost": 100.0}]}
        realized = compute_realized_pnl(session, baseline)

        assert realized.fill_totals[fill.id] == 10.0
        assert realized.order_totals[order.id] == 10.0
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_detail_realized_pnl.py::test_fill_detail_contains_realized_fields -v`
Expected: FAIL (missing mappings)

**Step 3: Update schemas**

```python
# backend/app/schemas.py (snippet)
class TradeFillDetailOut(BaseModel):
    id: int
    order_id: int
    symbol: str | None = None
    side: str | None = None
    exec_id: str | None = None
    fill_quantity: float
    fill_price: float
    commission: float | None = None
    realized_pnl: float | None = None
    fill_time: datetime | None = None
    currency: str | None = None
    exchange: str | None = None

class TradeOrderOut(BaseModel):
    # ...
    realized_pnl: float | None = None

class TradeReceiptOut(BaseModel):
    # ...
    commission: float | None = None
    realized_pnl: float | None = None
```

**Step 4: Build realized mapping in trade_run_summary**

```python
# backend/app/services/trade_run_summary.py (snippet)
from app.services.realized_pnl_baseline import ensure_positions_baseline
from app.services.realized_pnl import compute_realized_pnl
from app.services.lean_bridge_paths import resolve_bridge_root

# inside build_trade_run_detail
baseline = ensure_positions_baseline(resolve_bridge_root(), read_positions_payload)
realized = compute_realized_pnl(session, baseline)
# build fill dicts with symbol/side/commission/realized_pnl
```

**Step 5: Update trade_receipts**

```python
# backend/app/services/trade_receipts.py
# build realized mapping and attach commission/realized_pnl for fill + order receipts
```

**Step 6: Update trade routes for detail/orders/receipts**

```python
# backend/app/routes/trade.py
# when constructing fills/orders, pass dicts to TradeFillDetailOut/TradeOrderOut
```

**Step 7: Run tests**

Run: `pytest backend/tests/test_trade_detail_realized_pnl.py::test_fill_detail_contains_realized_fields -v`
Expected: PASS

**Step 8: Commit**

```bash
git add backend/app/services/trade_run_summary.py backend/app/services/trade_receipts.py backend/app/routes/trade.py backend/app/schemas.py backend/tests/test_trade_detail_realized_pnl.py

git commit -m "feat: expose realized pnl in trade details"
```

---

### Task 4: 前端表格新增列 + 已实现盈亏展示

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css`

**Step 1: Update types + columns**

```tsx
// LiveTradePage.tsx
interface IBAccountPosition { realized_pnl?: number; }
interface TradeFillDetail { realized_pnl?: number; commission?: number; symbol?: string; side?: string; }
interface TradeOrder { realized_pnl?: number; }
interface TradeReceipt { realized_pnl?: number; commission?: number; }
```

**Step 2: Render columns**

```tsx
// positions table: add column "已实现盈亏"
// fills table: add symbol/side/commission/realized_pnl columns
// orders table: add realized_pnl column
// receipts table: add commission/realized_pnl columns
```

**Step 3: Add i18n keys**

```ts
// i18n.tsx
trade: {
  realizedPnl: "已实现盈亏",
  commission: "手续费",
}
```

**Step 4: Run frontend build**

Run: `cd frontend && npm run build`

**Step 5: Restart frontend service**

Run: `systemctl --user restart stocklean-frontend`

**Step 6: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/src/styles.css

git commit -m "feat: show realized pnl in live trade tables"
```

---

### Task 5: 验证

**Step 1: Run backend tests (targeted)**

Run: `pytest backend/tests/test_realized_pnl_fifo.py backend/tests/test_realized_pnl_baseline.py backend/tests/test_trade_detail_realized_pnl.py -v`
Expected: PASS

**Step 2: Manual UI check (Playwright)**

- 打开实盘交易页面
- 检查“当前持仓/订单明细/成交明细/回执”新增列
- 确认已实现盈亏为非空数值（无成交显示 0）

---

Plan complete and saved to `docs/plans/2026-01-31-live-trade-realized-pnl-implementation.md`. Two execution options:

1. Subagent-Driven (this session) – I dispatch a fresh subagent per task, review between tasks
2. Parallel Session (separate) – Open new session with executing-plans

Which approach?
