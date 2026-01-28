# Manual Lean Order Execution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让“手动买/卖/平仓”在创建订单后立即生成 execution-intent 并启动 Lean IB 执行，同时用 execution_events 回写更新订单状态。

**Architecture:** 订单创建路由在 `params.source=manual` 时触发 manual execution 服务；该服务生成 intent 文件并调用 Lean Launcher；回写文件（JSONL）由后台解析并按 tag 更新订单。

**Tech Stack:** FastAPI + SQLAlchemy, Lean Launcher, Playwright

---

### Task 1: JSONL 回写入口测试

**Files:**
- Modify: `backend/tests/test_lean_execution_event_ingest.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import lean_execution


def test_ingest_events_jsonl_calls_apply(monkeypatch, tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text('{"tag": "oi_1", "status": "Submitted"}\n{"tag": "oi_1", "status": "Filled", "filled": 1, "fill_price": 10}\n')
    calls = {"payload": None}

    def _fake_apply(events):
        calls["payload"] = events

    monkeypatch.setattr(lean_execution, "apply_execution_events", _fake_apply, raising=False)

    lean_execution.ingest_execution_events(str(events_path))
    assert calls["payload"] is not None
    assert len(calls["payload"]) == 2
```

**Step 2: Run test to verify it fails**

Run:
```
pytest backend/tests/test_lean_execution_event_ingest.py::test_ingest_events_jsonl_calls_apply -q
```
Expected: FAIL（JSONL 尚未支持）

**Step 3: Implement minimal code to make the test pass**
- Update `backend/app/services/lean_execution.py`:
  - `ingest_execution_events` 支持 JSONL 行解析（忽略空行/坏行）

**Step 4: Run test to verify it passes**

Run:
```
pytest backend/tests/test_lean_execution_event_ingest.py::test_ingest_events_jsonl_calls_apply -q
```
Expected: PASS

**Step 5: Commit**
```
git add backend/app/services/lean_execution.py backend/tests/test_lean_execution_event_ingest.py
git commit -m "test: cover jsonl execution event ingest"
```

---

### Task 2: 回写事件更新订单状态（按 tag 匹配）

**Files:**
- Create: `backend/tests/test_trade_execution_event_apply.py`
- Modify: `backend/app/services/lean_execution.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services import lean_execution
from app.services.trade_orders import create_trade_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_apply_execution_events_updates_order(monkeypatch):
    session = _make_session()
    try:
        payload = {
            "client_order_id": "oi_0_0_123",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        session.commit()

        def _session_factory():
            return session

        monkeypatch.setattr(lean_execution, "SessionLocal", _session_factory, raising=False)

        events = [
            {"tag": "oi_0_0_123", "status": "Submitted", "order_id": 1001, "time": "2026-01-28T00:00:00Z"},
            {"tag": "oi_0_0_123", "status": "Filled", "filled": 1, "fill_price": 100.0, "time": "2026-01-28T00:00:01Z"},
        ]
        lean_execution.apply_execution_events(events)

        session.refresh(result.order)
        assert result.order.status == "FILLED"
        assert result.order.filled_quantity == 1
        assert result.order.avg_fill_price == 100.0
        assert result.order.ib_order_id == 1001
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run:
```
pytest backend/tests/test_trade_execution_event_apply.py::test_apply_execution_events_updates_order -q
```
Expected: FAIL（apply_execution_events 未实现）

**Step 3: Write minimal implementation**
- `backend/app/services/lean_execution.py`:
  - 实现 `apply_execution_events`：
    - 取 `tag` → 查 `TradeOrder.client_order_id`
    - `Submitted` → `update_trade_order_status(..., status="SUBMITTED")`
    - `Filled` → `apply_fill_to_order(...)`
    - 更新 `ib_order_id`，`last_status_ts`
    - 忽略 tag 缺失或订单不存在

**Step 4: Run test to verify it passes**

Run:
```
pytest backend/tests/test_trade_execution_event_apply.py::test_apply_execution_events_updates_order -q
```
Expected: PASS

**Step 5: Commit**
```
git add backend/app/services/lean_execution.py backend/tests/test_trade_execution_event_apply.py
git commit -m "feat: apply lean execution events by tag"
```

---

### Task 3: 手动订单 intent 生成与执行服务

**Files:**
- Create: `backend/app/services/manual_trade_execution.py`
- Create: `backend/tests/test_manual_trade_execution.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services.trade_orders import create_trade_order
from app.services.manual_trade_execution import write_manual_order_intent


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_write_manual_order_intent_builds_quantity(tmp_path):
    session = _make_session()
    try:
        payload = {
            "client_order_id": "oi_0_0_123",
            "symbol": "AAPL",
            "side": "SELL",
            "quantity": 1,
            "order_type": "MKT",
        }
        order = create_trade_order(session, payload).order
        session.commit()

        path = write_manual_order_intent(order, output_dir=tmp_path)
        text = Path(path).read_text(encoding="utf-8")
        assert "order_intent_id" in text
        assert "oi_0_0_123" in text
        assert "\"quantity\": -1" in text
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run:
```
pytest backend/tests/test_manual_trade_execution.py::test_write_manual_order_intent_builds_quantity -q
```
Expected: FAIL（服务尚未实现）

**Step 3: Write minimal implementation**
- `backend/app/services/manual_trade_execution.py`:
  - `write_manual_order_intent(order, output_dir)`：
    - SELL → quantity 负数；BUY → 正数
    - JSON 字段：`order_intent_id`, `symbol`, `quantity`, `weight`

**Step 4: Run test to verify it passes**

Run:
```
pytest backend/tests/test_manual_trade_execution.py::test_write_manual_order_intent_builds_quantity -q
```
Expected: PASS

**Step 5: Commit**
```
git add backend/app/services/manual_trade_execution.py backend/tests/test_manual_trade_execution.py
git commit -m "feat: build manual order intent"
```

---

### Task 4: 手动订单执行入口（触发 Lean）

**Files:**
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/services/manual_trade_execution.py`

**Step 1: Write the failing test**
- 在 `backend/tests/test_manual_trade_execution.py` 中新增：

```python
from app.services import manual_trade_execution


def test_execute_manual_order_launches(monkeypatch, tmp_path):
    calls = {"launched": False}

    def _fake_launch(config_path: str):
        calls["launched"] = True

    monkeypatch.setattr(manual_trade_execution, "launch_execution", _fake_launch, raising=False)

    # TODO: 生成 order + project_id/mode，然后调用 execute_manual_order
    # 断言 calls["launched"] 为 True
```

**Step 2: Run test to verify it fails**

Run:
```
pytest backend/tests/test_manual_trade_execution.py::test_execute_manual_order_launches -q
```
Expected: FAIL

**Step 3: Write minimal implementation**
- `manual_trade_execution.execute_manual_order(session, order, project_id, mode)`
  - 写 intent 文件
  - `build_execution_config(...)
  - `launch_execution(...)`
  - 订单 params 记录 `manual_execution` 元数据

**Step 4: Run test to verify it passes**

Run:
```
pytest backend/tests/test_manual_trade_execution.py::test_execute_manual_order_launches -q
```
Expected: PASS

**Step 5: Commit**
```
git add backend/app/routes/trade.py backend/app/services/manual_trade_execution.py backend/tests/test_manual_trade_execution.py
git commit -m "feat: launch lean execution for manual orders"
```

---

### Task 5: 前端手动订单注入 params

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`

**Step 1: Write the failing test**
- 新增 `frontend/tests/live-trade-manual-orders.spec.ts`（仅在 `PLAYWRIGHT_LIVE_TRADE=1` 时运行）

```ts
import { test, expect } from "@playwright/test";

const shouldRun = process.env.PLAYWRIGHT_LIVE_TRADE === "1";

test("manual buy/sell triggers trade orders", async ({ page }) => {
  test.skip(!shouldRun, "requires PLAYWRIGHT_LIVE_TRADE=1");
  await page.goto("/live-trade");
  const table = page.getByTestId("account-positions-table");
  await expect(table).toBeVisible();
  const row = table.locator("tbody tr").first();
  await row.locator("input[type=number]").fill("1");
  await row.getByRole("button", { name: /买入|Buy/i }).click();
  await row.getByRole("button", { name: /卖出|Sell/i }).click();
});
```

**Step 2: Run test to verify it fails**

Run:
```
PLAYWRIGHT_LIVE_TRADE=1 npx playwright test live-trade-manual-orders.spec.ts --reporter=line
```
Expected: FAIL（params 尚未注入，后端不触发执行）

**Step 3: Write minimal implementation**
- 在 `handlePositionOrder` / `handleClosePositions` / `handleLiquidateAll` 里：
  - `params.source = "manual"`
  - `params.project_id = selectedProjectId`
  - `params.mode = ibSettings?.mode || ibSettingsForm.mode || "paper"`

**Step 4: Run test to verify it passes**

Run:
```
PLAYWRIGHT_LIVE_TRADE=1 npx playwright test live-trade-manual-orders.spec.ts --reporter=line
```
Expected: PASS

**Step 5: Commit**
```
git add frontend/src/pages/LiveTradePage.tsx frontend/tests/live-trade-manual-orders.spec.ts
git commit -m "feat: mark manual orders with execution params"
```

---

### Task 6: 订单列表回写刷新

**Files:**
- Modify: `backend/app/routes/trade.py`

**Step 1: Write the failing test**
- 在 `backend/tests/test_trade_orders.py` 增加：
  - mock 一个 JSONL 回写文件
  - 调用 `/api/trade/orders` 前触发 ingest

**Step 2: Run test to verify it fails**

Run:
```
pytest backend/tests/test_trade_orders.py::test_orders_trigger_ingest -q
```
Expected: FAIL

**Step 3: Write minimal implementation**
- `list_trade_orders` 中调用 `ingest_execution_events`（若文件存在）

**Step 4: Run test to verify it passes**

Run:
```
pytest backend/tests/test_trade_orders.py::test_orders_trigger_ingest -q
```
Expected: PASS

**Step 5: Commit**
```
git add backend/app/routes/trade.py backend/tests/test_trade_orders.py
git commit -m "feat: ingest execution events on order listing"
```

---

### Task 7: 集成验证

**Files:**
- None

**Step 1: Backend tests**

Run:
```
pytest backend/tests/test_lean_execution_event_ingest.py \
  backend/tests/test_trade_execution_event_apply.py \
  backend/tests/test_manual_trade_execution.py -q
```
Expected: PASS

**Step 2: Playwright**

Run:
```
PLAYWRIGHT_LIVE_TRADE=1 npx playwright test live-trade-manual-orders.spec.ts --reporter=line
```
Expected: PASS

**Step 3: Commit (if needed)**

```
git status
```

---

Plan complete and saved to `docs/plans/2026-01-28-manual-lean-order-execution.md`. Two execution options:

1. Subagent-Driven (this session) – I dispatch fresh subagent per task, review between tasks
2. Parallel Session (separate) – Open new session with executing-plans, batch execution with checkpoints

Which approach?
