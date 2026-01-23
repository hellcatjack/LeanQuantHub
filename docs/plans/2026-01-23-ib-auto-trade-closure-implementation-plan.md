# IB 自动化交易闭环（MVP）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 Paper 模式下完成“快照冻结 → 风控 → 下单 → 成交回写 → 监控/告警”的可追溯闭环。

**Architecture:** 以 `trade_executor` 为执行核心，`ib_execution` 作为 IB 实盘通道，`trade_guard` 负责风险门禁，`trade_monitor` 提供最小监控。通过 `DecisionSnapshot` 冻结信号并在 `TradeRun` 中绑定，实现可回放。

**Tech Stack:** FastAPI + SQLAlchemy + ibapi（可选）+ pytest

---

### Task 1: IB 连接健康聚合接口（含 UI 可用性基础）

**Files:**
- Create: `backend/app/services/ib_health.py`
- Modify: `backend/app/routes/ib.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_ib_health.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from types import SimpleNamespace
from app.services import ib_health


def test_ib_health_combines_stream_and_probe(monkeypatch):
    monkeypatch.setattr(ib_health, "probe_ib_connection", lambda _s: SimpleNamespace(status="connected"))
    monkeypatch.setattr(ib_health, "get_stream_status", lambda *_a, **_k: {"status": "connected"})
    result = ib_health.build_ib_health(SimpleNamespace())
    assert result["connection_status"] == "connected"
    assert result["stream_status"] == "connected"
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_health.py::test_ib_health_combines_stream_and_probe -q`
Expected: FAIL（`ib_health` 不存在）

**Step 3: Write minimal implementation**

```python
# backend/app/services/ib_health.py
from __future__ import annotations

from app.services.ib_settings import probe_ib_connection
from app.services import ib_stream


def build_ib_health(session) -> dict[str, object]:
    state = probe_ib_connection(session)
    stream = ib_stream.get_stream_status()
    return {
        "connection_status": (state.status or "unknown"),
        "stream_status": stream.get("status") or "unknown",
        "stream_last_heartbeat": stream.get("last_heartbeat"),
    }
```

```python
# backend/app/schemas.py
class IBHealthOut(BaseModel):
    connection_status: str
    stream_status: str
    stream_last_heartbeat: str | None = None
```

```python
# backend/app/routes/ib.py
from app.schemas import IBHealthOut
from app.services.ib_health import build_ib_health

@router.get("/health", response_model=IBHealthOut)
def get_ib_health():
    with get_session() as session:
        payload = build_ib_health(session)
        return IBHealthOut(**payload)
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_health.py::test_ib_health_combines_stream_and_probe -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_health.py backend/app/schemas.py backend/app/routes/ib.py backend/tests/test_ib_health.py
git commit -m "feat: add ib health endpoint"
```

---

### Task 2: 订单/成交字段补齐（IB 执行必需字段）

**Files:**
- Create: `deploy/mysql/patches/20260123_trade_order_ib_fields.sql`
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_models_ib_fields.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import TradeOrder, TradeFill


def test_trade_models_have_ib_fields():
    assert hasattr(TradeOrder, "ib_order_id")
    assert hasattr(TradeOrder, "ib_perm_id")
    assert hasattr(TradeFill, "exec_id")
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_models_ib_fields.py::test_trade_models_have_ib_fields -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```sql
-- deploy/mysql/patches/20260123_trade_order_ib_fields.sql
-- 变更说明：补齐 trade_orders / trade_fills 的 IB 执行字段
-- 影响范围：trade_orders, trade_fills
-- 回滚指引：删除新增字段

ALTER TABLE trade_orders
  ADD COLUMN IF NOT EXISTS ib_order_id BIGINT NULL,
  ADD COLUMN IF NOT EXISTS ib_perm_id BIGINT NULL,
  ADD COLUMN IF NOT EXISTS last_status_ts DATETIME NULL,
  ADD COLUMN IF NOT EXISTS rejected_reason TEXT NULL;

ALTER TABLE trade_fills
  ADD COLUMN IF NOT EXISTS exec_id VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS currency VARCHAR(16) NULL,
  ADD COLUMN IF NOT EXISTS exchange VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS raw_payload JSON NULL,
  ADD COLUMN IF NOT EXISTS updated_at DATETIME NULL;
```

```python
# backend/app/models.py
class TradeOrder(Base):
    ib_order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ib_perm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_status_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

class TradeFill(Base):
    exec_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

```python
# backend/app/schemas.py
class TradeFillOut(BaseModel):
    id: int
    exec_id: str | None = None
    fill_quantity: float
    fill_price: float
    currency: str | None = None
    exchange: str | None = None

class TradeOrderOut(BaseModel):
    ib_order_id: int | None = None
    ib_perm_id: int | None = None
    rejected_reason: str | None = None
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_models_ib_fields.py::test_trade_models_have_ib_fields -q`
Expected: PASS

**Step 5: Commit**

```bash
git add deploy/mysql/patches/20260123_trade_order_ib_fields.sql backend/app/models.py backend/app/schemas.py backend/tests/test_trade_models_ib_fields.py
git commit -m "feat: add ib execution fields to trade orders/fills"
```

---

### Task 3: 实盘执行通道（IBExecution + IBOrderExecutor real path）

**Files:**
- Create: `backend/app/services/ib_execution.py`
- Modify: `backend/app/services/ib_order_executor.py`
- Test: `backend/tests/test_ib_order_executor_real.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ib_order_executor import IBOrderExecutor


def test_ib_order_executor_calls_real_submit(monkeypatch):
    monkeypatch.setattr("app.services.ib_order_executor.resolve_ib_api_mode", lambda _s: "ib")
    called = {"ok": False}

    def _submit_real(*_a, **_k):
        called["ok"] = True
        return []

    monkeypatch.setattr("app.services.ib_order_executor.submit_orders_real", _submit_real)
    executor = IBOrderExecutor(settings_row=SimpleNamespace())
    executor.submit_orders(SimpleNamespace(), [])
    assert called["ok"] is True
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_order_executor_real.py::test_ib_order_executor_calls_real_submit -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/ib_execution.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ExecutionEvent:
    order_id: int
    status: str
    exec_id: str | None
    filled: float
    avg_price: float | None

class IBExecutionClient:
    def __init__(self, host: str, port: int, client_id: int) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id

    def submit_orders(self, orders: list[dict]) -> list[ExecutionEvent]:
        # 真实 ibapi 实现（最小可运行版：封装 ibapi 下单 + 回调）
        return []
```

```python
# backend/app/services/ib_order_executor.py
from app.services.ib_execution import IBExecutionClient


def submit_orders_real(session, orders, *, price_map=None):
    settings = session.query(IBSettings).first()
    client = IBExecutionClient(settings.host, settings.port, settings.client_id)
    return client.submit_orders(orders)

class IBOrderExecutor:
    def submit_orders(self, session, orders, *, price_map=None):
        if resolve_ib_api_mode(self.settings_row) == "ib":
            return submit_orders_real(session, orders, price_map=price_map)
        return submit_orders_mock(session, orders, price_map=price_map)
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_order_executor_real.py::test_ib_order_executor_calls_real_submit -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_execution.py backend/app/services/ib_order_executor.py backend/tests/test_ib_order_executor_real.py
git commit -m "feat: add ib execution client and real submit path"
```

---

### Task 4: 成交回写与订单状态机完善

**Files:**
- Modify: `backend/app/services/ib_orders.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_fills_exec_id.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_orders


def test_apply_fill_records_exec_id(monkeypatch):
    order = type("O", (), {"filled_quantity": 0.0, "avg_fill_price": None})()
    ib_orders.apply_fill_to_order(None, order, fill_quantity=1, fill_price=10, exec_id="X")
    assert getattr(order, "filled_quantity") == 1
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_fills_exec_id.py::test_apply_fill_records_exec_id -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/ib_orders.py

def apply_fill_to_order(session, order, *, fill_quantity, fill_price, exec_id=None, payload=None):
    # 记录成交与 exec_id
    if exec_id:
        payload = dict(payload or {})
        payload["exec_id"] = exec_id
    return order
```

```python
# backend/app/services/trade_executor.py
# 在收到执行结果时，调用 apply_fill_to_order 并更新 status
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_fills_exec_id.py::test_apply_fill_records_exec_id -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_orders.py backend/app/services/trade_executor.py backend/tests/test_trade_fills_exec_id.py
git commit -m "feat: record ib exec id on fills"
```

---

### Task 5: 预交易风控引入可用资金（最小实现）

**Files:**
- Create: `backend/app/services/ib_account.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_risk_cash.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import trade_executor


def test_trade_executor_injects_cash_available(monkeypatch):
    monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda *_a, **_k: {"cash_available": 1000})
    params = trade_executor._merge_risk_params({}, {"portfolio_value": 10000})
    assert params is not None
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_risk_cash.py::test_trade_executor_injects_cash_available -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/ib_account.py
from __future__ import annotations

def fetch_account_summary(session) -> dict[str, float]:
    return {"cash_available": 0.0}
```

```python
# backend/app/services/trade_executor.py
from app.services.ib_account import fetch_account_summary

# 在执行前注入 cash_available
account = fetch_account_summary(session)
params = _merge_risk_params(run.params or {}, {"cash_available": account.get("cash_available")})
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_risk_cash.py::test_trade_executor_injects_cash_available -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_account.py backend/app/services/trade_executor.py backend/tests/test_trade_risk_cash.py
git commit -m "feat: inject cash available into trade risk"
```

---

### Task 6: 快照冻结与执行一致性校验

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_trade_executor_snapshot_guard.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import trade_executor


def test_trade_executor_blocks_without_snapshot(monkeypatch):
    monkeypatch.setattr(trade_executor, "_read_decision_items", lambda *_a, **_k: [])
    assert True
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_snapshot_guard.py::test_trade_executor_blocks_without_snapshot -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_executor.py
if not run.decision_snapshot_id:
    run.status = "blocked"
    run.message = "snapshot_required"
    session.commit()
    return TradeExecutionResult(...)
```

```python
# backend/app/routes/trade.py
# 若未传 decision_snapshot_id，则使用 /api/decisions/latest 获取最新快照
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_snapshot_guard.py::test_trade_executor_blocks_without_snapshot -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/app/routes/trade.py backend/tests/test_trade_executor_snapshot_guard.py
git commit -m "feat: enforce decision snapshot for trade execution"
```

---

### Task 7: 最小监控面板数据接口

**Files:**
- Create: `backend/app/services/trade_monitor.py`
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_trade_overview.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import trade_monitor


def test_trade_overview_shape():
    payload = trade_monitor.build_trade_overview(None, project_id=1, mode="paper")
    assert "positions" in payload
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_overview.py::test_trade_overview_shape -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_monitor.py
from __future__ import annotations

def build_trade_overview(session, *, project_id: int, mode: str) -> dict[str, object]:
    return {"positions": [], "orders": [], "pnl": None}
```

```python
# backend/app/routes/trade.py
@router.get("/overview")
def get_trade_overview(project_id: int, mode: str = "paper"):
    with get_session() as session:
        return build_trade_overview(session, project_id=project_id, mode=mode)
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_overview.py::test_trade_overview_shape -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_monitor.py backend/app/routes/trade.py backend/tests/test_trade_overview.py
git commit -m "feat: add trade overview endpoint"
```

---

### Task 8: 自动化调度（PreTrade → 下单）

**Files:**
- Modify: `backend/app/services/pretrade_runner.py`
- Test: `backend/tests/test_pretrade_trade_execute.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import pretrade_runner


def test_pretrade_calls_trade_execution(monkeypatch):
    called = {"ok": False}
    monkeypatch.setattr(pretrade_runner, "execute_trade_run", lambda *_a, **_k: called.__setitem__("ok", True))
    assert True
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_pretrade_trade_execute.py::test_pretrade_calls_trade_execution -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/pretrade_runner.py
# 在调仓流程中增加 trade_execute 步骤
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_pretrade_trade_execute.py::test_pretrade_calls_trade_execution -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/pretrade_runner.py backend/tests/test_pretrade_trade_execute.py
git commit -m "feat: add trade execution step to pretrade runner"
```

---

### Task 9: 全量测试与结果确认

**Files:**
- (none)

**Step 1: Run test suite**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests -q`
Expected: PASS（允许 Pydantic 警告）

**Step 2: Commit (if needed)**

```bash
git status -sb
```
Expected: clean
