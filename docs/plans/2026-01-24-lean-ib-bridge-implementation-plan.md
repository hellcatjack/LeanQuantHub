# Lean IB Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成 Lean 输出桥接接入，移除所有 IB API 直连执行与数据链路，系统内可视化仅从 Lean Bridge 输出读取。

**Architecture:** 交易执行由 `trade_executor` 仅生成订单意图并触发 Lean 执行；新增 `lean_bridge` 服务读取 Lean 输出文件并写入缓存/DB；`/api/ib/*` 改为读取桥接数据；删除 IB 直连执行与行情/账户/stream 模块与测试。

**Tech Stack:** FastAPI, SQLAlchemy, Python, JSON/JSONL, Lean Engine

## 实施调整记录（2026-01-24）
- 实际落地使用 `lean_bridge_reader.py` 作为读取层，未新增 `lean_bridge.py` 写缓存模块。
- `/api/ib/*` 已改为直接读取 Lean Bridge 输出（状态/行情/账户）。
- `ib_market.py` 改为 Lean Bridge 行情读取实现；历史/合约刷新返回 `unsupported`。
- `ib_account.py` 精简为仅从 Lean Bridge 读取账户/持仓。
- 清理：移除 `ib_execution.py`/`ib_order_executor.py`/`ib_stream_runner.py`/`ib_history_runner.py` 及脚本与测试。

---

### Task 1: Lean Bridge 读取与缓存（account/positions/quotes）

**Files:**
- Create: `backend/app/services/lean_bridge.py`
- Create: `backend/tests/test_lean_bridge_cache.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import sys
import json

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_bridge


def test_write_bridge_cache(tmp_path, monkeypatch):
    bridge_root = tmp_path / "lean_bridge"
    bridge_root.mkdir()
    (bridge_root / "account_summary.json").write_text(json.dumps({"NetLiquidation": 100}))
    (bridge_root / "positions.json").write_text("[]")
    (bridge_root / "quotes.json").write_text("[]")

    cache_root = tmp_path / "cache"
    monkeypatch.setattr(lean_bridge, "BRIDGE_ROOT", bridge_root, raising=False)
    monkeypatch.setattr(lean_bridge, "CACHE_ROOT", cache_root, raising=False)

    lean_bridge.refresh_bridge_cache()

    assert (cache_root / "account_summary.json").exists()
    payload = json.loads((cache_root / "account_summary.json").read_text())
    assert payload.get("NetLiquidation") == 100
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_cache.py::test_write_bridge_cache`
Expected: FAIL (module/function missing)

**Step 3: Write minimal implementation**
```python
# backend/app/services/lean_bridge.py
from __future__ import annotations

import json
from pathlib import Path

BRIDGE_ROOT = Path("/app/stocklean/artifacts/lean_bridge")
CACHE_ROOT = Path("/app/stocklean/data/lean_bridge/cache")


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_bridge_cache() -> None:
    account = _read_json(BRIDGE_ROOT / "account_summary.json")
    positions = _read_json(BRIDGE_ROOT / "positions.json")
    quotes = _read_json(BRIDGE_ROOT / "quotes.json")
    if account is not None:
        _write_json(CACHE_ROOT / "account_summary.json", account)
    if positions is not None:
        _write_json(CACHE_ROOT / "positions.json", positions)
    if quotes is not None:
        _write_json(CACHE_ROOT / "quotes.json", quotes)
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_cache.py::test_write_bridge_cache`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/lean_bridge.py backend/tests/test_lean_bridge_cache.py
git commit -m "feat: add lean bridge cache refresh"
```

---

### Task 2: Lean Bridge 事件 ingest（写入 trade_orders/trade_fills）

**Files:**
- Modify: `backend/app/services/lean_bridge.py`
- Create: `backend/tests/test_lean_bridge_events.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import sys
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeOrder
from app.services import lean_bridge


def test_ingest_execution_events_updates_order(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(lean_bridge, "SessionLocal", Session, raising=False)

    session = Session()
    order = TradeOrder(run_id=1, symbol="AAPL", side="BUY", quantity=1, status="NEW")
    session.add(order)
    session.commit()
    order_id = order.id
    session.close()

    events_path = tmp_path / "execution_events.jsonl"
    events_path.write_text(json.dumps({"order_id": order_id, "status": "FILLED", "avg_price": 100, "filled": 1, "exec_id": "e1"}) + "\n")
    monkeypatch.setattr(lean_bridge, "BRIDGE_ROOT", tmp_path, raising=False)

    lean_bridge.ingest_execution_events()

    session = Session()
    refreshed = session.get(TradeOrder, order_id)
    assert refreshed.status == "FILLED"
    session.close()
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_events.py::test_ingest_execution_events_updates_order`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# in backend/app/services/lean_bridge.py
from app.db import SessionLocal
from app.models import TradeOrder


def ingest_execution_events() -> None:
    path = BRIDGE_ROOT / "execution_events.jsonl"
    if not path.exists():
        return
    session = SessionLocal()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            order_id = event.get("order_id")
            if not order_id:
                continue
            order = session.get(TradeOrder, int(order_id))
            if not order:
                continue
            status = str(event.get("status") or "").upper()
            if status:
                order.status = status
            if event.get("avg_price") is not None:
                order.avg_fill_price = float(event.get("avg_price"))
            if event.get("filled") is not None:
                order.filled_quantity = float(event.get("filled"))
        session.commit()
    finally:
        session.close()
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_bridge_events.py::test_ingest_execution_events_updates_order`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/lean_bridge.py backend/tests/test_lean_bridge_events.py
git commit -m "feat: ingest lean execution events"
```

---

### Task 3: /api/ib 读取改为 Lean Bridge 缓存

**Files:**
- Modify: `backend/app/routes/ib.py`
- Modify: `backend/app/services/ib_account.py`
- Create: `backend/tests/test_ib_routes_bridge.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import sys
import json

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_account


def test_get_account_summary_reads_bridge_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True)
    (cache_root / "account_summary.json").write_text(json.dumps({"NetLiquidation": 123}))
    monkeypatch.setattr(ib_account, "CACHE_ROOT", cache_root, raising=False)

    payload = ib_account.get_account_summary(mode="paper", full=False)
    assert payload.get("NetLiquidation") == 123
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_ib_routes_bridge.py::test_get_account_summary_reads_bridge_cache`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# in backend/app/services/ib_account.py
from pathlib import Path
import json

CACHE_ROOT = Path("/app/stocklean/data/lean_bridge/cache")

def get_account_summary(mode: str = "paper", full: bool = False) -> dict:
    path = CACHE_ROOT / "account_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_ib_routes_bridge.py::test_get_account_summary_reads_bridge_cache`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/ib_account.py backend/tests/test_ib_routes_bridge.py
git commit -m "refactor: ib account reads lean bridge cache"
```

---

### Task 4: 清理 IB 直连执行链路

**Files:**
- Delete: `backend/app/services/ib_execution.py`
- Delete: `backend/app/services/ib_order_executor.py`
- Delete: `backend/app/services/ib_orders.py`
- Modify: `backend/app/services/trade_executor.py`
- Delete tests: `backend/tests/test_ib_execution_client.py`, `backend/tests/test_ib_execution_events.py`, `backend/tests/test_ib_order_executor_real.py`, `backend/tests/test_ib_orders_mock.py`, `backend/tests/test_trade_executor_ib.py`

**Step 1: Write the failing test**
```python
# Use existing tests to fail by removing references (no new test)
```

**Step 2: Implement minimal changes**
- Remove IB execution imports from `trade_executor.py`.
- Ensure `trade_executor` only writes order intent and triggers `lean_execution.launch_execution` (to be added if missing).

**Step 3: Run tests to verify**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_trade_run_intent_path.py::test_trade_run_sets_order_intent_path`
Expected: PASS

**Step 4: Commit**
```bash
git add backend/app/services/trade_executor.py
git rm backend/app/services/ib_execution.py backend/app/services/ib_order_executor.py backend/app/services/ib_orders.py backend/tests/test_ib_execution_client.py backend/tests/test_ib_execution_events.py backend/tests/test_ib_order_executor_real.py backend/tests/test_ib_orders_mock.py backend/tests/test_trade_executor_ib.py
git commit -m "chore: remove direct ib execution path"
```

---

### Task 5: 清理 IB 行情/账户/stream 直连（改为桥接）

**Files:**
- Delete: `backend/app/services/ib_market.py`
- Delete: `backend/app/services/ib_stream.py`
- Delete: `backend/app/services/ib_stream_runner.py`
- Delete: `backend/app/services/ib_history_runner.py`
- Modify: `backend/app/routes/ib.py`
- Remove tests related to ib stream/history

**Step 1: Write the failing test**
```python
# Remove IB stream endpoints references (no new test)
```

**Step 2: Implement minimal changes**
- `routes/ib.py` only exposes read endpoints (account/positions/quotes/status) using Lean Bridge cache.
- Remove stream/history endpoints.

**Step 3: Run tests**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_ib_routes_bridge.py::test_get_account_summary_reads_bridge_cache`
Expected: PASS

**Step 4: Commit**
```bash
git rm backend/app/services/ib_market.py backend/app/services/ib_stream.py backend/app/services/ib_stream_runner.py backend/app/services/ib_history_runner.py
# remove related tests/files

git add backend/app/routes/ib.py

git commit -m "chore: remove ib api data path, use lean bridge"
```

---

## Verification Checklist
- 每个 Task 的测试必须先失败后通过。
- 每个 Task 完成后独立提交。
- 前端如涉及 UI 变更，需 `npm run build` 并重启前端服务。
