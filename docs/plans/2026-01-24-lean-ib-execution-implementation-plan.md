# Lean IB Execution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 接入 Lean IB 执行器，实现“逻辑一致”的实盘/模拟盘执行闭环，并保持现有 Alpha 研究/回测逻辑不变。

**Architecture:** 保留现有 `TradeRun/DecisionSnapshot` 作为信号源；新增“订单意图”文件作为执行输入；Lean 执行器读取意图并通过 IB Brokerage 下单；订单/成交事件回写到现有 `trade_orders`/`trade_fills`。

**Tech Stack:** FastAPI, SQLAlchemy, Lean Engine, IB Brokerage, CSV/JSON 意图文件, Python

---

### Task 1: 订单意图生成器（Order Intent）

**Files:**
- Create: `backend/app/services/trade_order_intent.py`
- Create: `backend/tests/test_trade_order_intent.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import json
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot
from app.services import trade_order_intent


def test_build_order_intent_writes_min_fields(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        snapshot = DecisionSnapshot(
            project_id=1,
            status="success",
            snapshot_date="2026-01-16",
            items_path=str(tmp_path / "items.csv"),
        )
        session.add(snapshot)
        session.commit()
        # mock items
        items = [
            {"symbol": "AAPL", "weight": 0.1, "snapshot_date": "2026-01-16", "rebalance_date": "2026-01-16"},
        ]
        output = trade_order_intent.write_order_intent(
            session,
            snapshot_id=snapshot.id,
            items=items,
            output_dir=tmp_path,
        )
        payload = json.loads(Path(output).read_text())
        assert payload[0]["symbol"] == "AAPL"
        assert "weight" in payload[0]
        assert "snapshot_date" in payload[0]
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_trade_order_intent.py::test_build_order_intent_writes_min_fields`
Expected: FAIL (module or function missing)

**Step 3: Write minimal implementation**
```python
# backend/app/services/trade_order_intent.py
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime


def write_order_intent(session, *, snapshot_id: int, items: list[dict], output_dir: Path) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"order_intent_snapshot_{snapshot_id}.json"
    payload = []
    for item in items:
        payload.append(
            {
                "symbol": item.get("symbol"),
                "weight": item.get("weight"),
                "snapshot_date": item.get("snapshot_date"),
                "rebalance_date": item.get("rebalance_date"),
            }
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_trade_order_intent.py::test_build_order_intent_writes_min_fields`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_order_intent.py backend/tests/test_trade_order_intent.py
git commit -m "feat: add order intent writer"
```

---

### Task 2: 在 TradeRun 执行中写入订单意图路径

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Create: `backend/tests/test_trade_run_intent_path.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from types import SimpleNamespace
from app.models import Base, DecisionSnapshot, TradeRun
import app.services.trade_executor as trade_executor


def test_trade_run_sets_order_intent_path(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "probe_ib_connection", lambda _s: SimpleNamespace(status="connected"))
    monkeypatch.setattr(trade_executor, "ensure_ib_client_id", lambda _s: SimpleNamespace())
    monkeypatch.setattr(trade_executor, "resolve_ib_api_mode", lambda _s: "mock")
    monkeypatch.setattr(trade_executor, "fetch_market_snapshots", lambda *a, **k: [])
    monkeypatch.setattr(trade_executor, "evaluate_orders", lambda *_a, **_k: (True, [], []))
    monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda *_a, **_k: {"NetLiquidation": 100000})
    monkeypatch.setattr(trade_executor, "_read_decision_items", lambda *_a, **_k: [{"symbol": "AAPL", "weight": 0.1}])
    monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

    session = Session()
    try:
        snapshot = DecisionSnapshot(project_id=1, status="success", snapshot_date="2026-01-16", items_path="dummy.csv")
        session.add(snapshot)
        session.commit()
        run = TradeRun(project_id=1, decision_snapshot_id=snapshot.id, mode="paper", status="queued", params={})
        session.add(run)
        session.commit()
    finally:
        session.close()

    trade_executor.execute_trade_run(run.id, dry_run=True)

    session = Session()
    try:
        refreshed = session.get(TradeRun, run.id)
        assert "order_intent_path" in (refreshed.params or {})
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_trade_run_intent_path.py::test_trade_run_sets_order_intent_path`
Expected: FAIL (missing order_intent_path)

**Step 3: Write minimal implementation**
```python
# in backend/app/services/trade_executor.py
from app.services.trade_order_intent import write_order_intent

# after reading decision items and before order building
artifact_root = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
intent_path = write_order_intent(
    session,
    snapshot_id=run.decision_snapshot_id,
    items=items,
    output_dir=artifact_root / "order_intents",
)
params["order_intent_path"] = intent_path
run.params = params
session.commit()
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_trade_run_intent_path.py::test_trade_run_sets_order_intent_path`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_run_intent_path.py
git commit -m "feat: record order intent path in trade runs"
```

---

### Task 3: Lean 执行配置生成器（Execution Config Builder）

**Files:**
- Create: `backend/app/services/lean_execution.py`
- Create: `backend/tests/test_lean_execution_config.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution


def test_build_execution_config_includes_intent_path(tmp_path):
    config = lean_execution.build_execution_config(
        intent_path=str(tmp_path / "intent.json"),
        brokerage="InteractiveBrokersBrokerage",
    )
    assert config["execution-intent-path"].endswith("intent.json")
    assert "brokerage" in config
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_config.py::test_build_execution_config_includes_intent_path`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# backend/app/services/lean_execution.py
from __future__ import annotations


def build_execution_config(*, intent_path: str, brokerage: str) -> dict:
    return {
        "brokerage": brokerage,
        "execution-intent-path": intent_path,
    }
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_config.py::test_build_execution_config_includes_intent_path`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/lean_execution.py backend/tests/test_lean_execution_config.py
git commit -m "feat: add lean execution config builder"
```

---

### Task 4: Lean 执行器入口（启动 Lean 执行进程）

**Files:**
- Modify: `backend/app/services/lean_execution.py`
- Create: `backend/tests/test_lean_execution_runner.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution


def test_launch_execution_calls_subprocess(monkeypatch, tmp_path):
    calls = {}
    def _fake_run(cmd, check):
        calls["cmd"] = cmd
    monkeypatch.setattr(lean_execution, "subprocess_run", _fake_run, raising=False)

    lean_execution.launch_execution(
        config_path=str(tmp_path / "lean-config.json"),
    )
    assert "lean-config.json" in " ".join(calls["cmd"])
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_runner.py::test_launch_execution_calls_subprocess`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# backend/app/services/lean_execution.py
import subprocess

subprocess_run = subprocess.run


def launch_execution(*, config_path: str) -> None:
    cmd = ["dotnet", "QuantConnect.Lean.Launcher.dll", "--config", config_path]
    subprocess_run(cmd, check=False)
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_runner.py::test_launch_execution_calls_subprocess`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/lean_execution.py backend/tests/test_lean_execution_runner.py
git commit -m "feat: add lean execution runner entry"
```

---

### Task 5: 执行事件回写（OrderEvent → trade_orders/trade_fills）

**Files:**
- Modify: `backend/app/services/lean_execution.py`
- Create: `backend/tests/test_lean_execution_event_ingest.py`

**Step 1: Write the failing test**
```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution


def test_ingest_events_updates_orders(monkeypatch, tmp_path):
    events_path = tmp_path / "events.json"
    events_path.write_text('[{"order_id": 1, "status": "FILLED", "fill_price": 100}]')
    calls = {"updated": False}

    def _fake_apply(*args, **kwargs):
        calls["updated"] = True

    monkeypatch.setattr(lean_execution, "apply_execution_events", _fake_apply, raising=False)

    lean_execution.ingest_execution_events(str(events_path))
    assert calls["updated"]
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_event_ingest.py::test_ingest_events_updates_orders`
Expected: FAIL

**Step 3: Write minimal implementation**
```python
# backend/app/services/lean_execution.py
import json


def ingest_execution_events(path: str) -> None:
    events = json.loads(Path(path).read_text())
    apply_execution_events(events)


def apply_execution_events(events: list[dict]) -> None:
    # TODO: update trade_orders / trade_fills in DB
    pass
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/pytest -q backend/tests/test_lean_execution_event_ingest.py::test_ingest_events_updates_orders`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/lean_execution.py backend/tests/test_lean_execution_event_ingest.py
git commit -m "feat: add lean execution event ingest skeleton"
```

---

### Task 6: 更新 TODO 与对账展示入口

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Write the failing test**
```python
# docs/todolists are not code-tested; skip test.
```

**Step 2: Implement**
- 标记 Phase 2.3/4.3/5 偏差展示为进行中（[ ] → [~] 或 [ ] 留待实现）
- 添加“Lean Execution Provider 接入”验收项

**Step 3: Commit**
```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: align IB auto trade TODO with lean execution plan"
```

---

## Verification Checklist
- 每个 Task 的测试必须先失败后通过。
- 每个 Task 完成后独立提交。

---

## References
- `docs/plans/2026-01-24-lean-ib-execution-design.md`
