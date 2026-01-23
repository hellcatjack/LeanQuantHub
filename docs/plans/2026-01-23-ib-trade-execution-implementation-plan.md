# IB Trade Execution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Paper+Live manual trade execution with MKT-only orders and mandatory fills write-back.

**Architecture:** Synchronous execution in `trade_executor` with a dedicated IB execution client that sends orders and listens for `orderStatus/execDetails` callbacks. Orders and fills are written to DB with idempotent clientOrderId mapping.

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, ibapi (EClient/EWrapper), pytest

---

### Task 1: Add DB patch for trade_fills and order columns

**Files:**
- Create: `deploy/mysql/patches/20260123_trade_fills_and_orders.sql`

**Step 1: Write the migration script (idempotent)**

```sql
-- 变更说明：新增 trade_fills 表，扩展 trade_orders 字段用于 IB 回报映射
-- 影响范围：trade_orders / trade_fills
-- 回滚指引：删除新增字段与 trade_fills 表

-- 1) trade_fills
CREATE TABLE IF NOT EXISTS trade_fills (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL,
  exec_id VARCHAR(64) NOT NULL,
  filled_qty DOUBLE NOT NULL,
  price DOUBLE NOT NULL,
  commission DOUBLE NULL,
  trade_time DATETIME NULL,
  currency VARCHAR(8) NULL,
  exchange VARCHAR(32) NULL,
  raw_payload JSON NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_trade_fills_exec_id (exec_id),
  KEY idx_trade_fills_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) trade_orders columns (check information_schema before ALTER)
-- ib_order_id
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'ib_order_id'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN ib_order_id INT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ib_perm_id
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'ib_perm_id'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN ib_perm_id INT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- last_status_ts
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'last_status_ts'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN last_status_ts DATETIME NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- rejected_reason
SET @col_exists := (
  SELECT COUNT(1) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_orders'
    AND COLUMN_NAME = 'rejected_reason'
);
SET @sql := IF(@col_exists = 0, 'ALTER TABLE trade_orders ADD COLUMN rejected_reason TEXT NULL', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
```

**Step 2: Verify script exists and is readable**

Run: `ls -l deploy/mysql/patches/20260123_trade_fills_and_orders.sql`
Expected: file exists

**Step 3: Commit**

```bash
git add deploy/mysql/patches/20260123_trade_fills_and_orders.sql
git commit -m "db: add trade_fills and ib order columns"
```

---

### Task 2: Add TradeFill model + extend TradeOrder

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_models.py`

**Step 1: Write failing test**

```python
from app.models import TradeOrder, TradeFill

def test_trade_fill_fields_exist():
    fill = TradeFill(
        order_id=1,
        exec_id="E1",
        filled_qty=10,
        price=100,
        commission=1.2,
    )
    assert fill.exec_id == "E1"
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_models.py::test_trade_fill_fields_exist -q`
Expected: FAIL (TradeFill missing)

**Step 3: Implement minimal model + schema**

```python
class TradeFill(Base):
    __tablename__ = "trade_fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("trade_orders.id"), nullable=False)
    exec_id: Mapped[str] = mapped_column(String(64), nullable=False)
    filled_qty: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Extend `TradeOrder` with new columns: `ib_order_id, ib_perm_id, last_status_ts, rejected_reason`.
Add Pydantic outputs: `TradeFillOut`, update `TradeOrderOut` to include optional `fills` list.

**Step 4: Run tests**

Run: `pytest backend/tests/test_trade_models.py::test_trade_fill_fields_exist -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/models.py backend/app/schemas.py backend/tests/test_trade_models.py
git commit -m "feat: add trade fill model and order fields"
```

---

### Task 3: IB execution client (order submit + callbacks)

**Files:**
- Create: `backend/app/services/ib_execution.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_ib_execution.py`

**Step 1: Write failing test (callback capture)**

```python
from app.services.ib_execution import ExecutionEventBuffer

def test_execution_event_buffer_records_updates():
    buf = ExecutionEventBuffer()
    buf.on_order_status(order_id=1, status="Submitted")
    buf.on_execution(exec_id="E1", order_id=1, qty=10, price=100.0)
    assert buf.order_statuses[1] == "Submitted"
    assert buf.executions["E1"]["qty"] == 10
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_execution.py::test_execution_event_buffer_records_updates -q`
Expected: FAIL (module missing)

**Step 3: Implement minimal buffer + IB client wrapper**

```python
class ExecutionEventBuffer:
    def __init__(self):
        self.order_statuses = {}
        self.executions = {}
    def on_order_status(self, order_id, status):
        self.order_statuses[order_id] = status
    def on_execution(self, exec_id, order_id, qty, price, **kwargs):
        self.executions[exec_id] = {"order_id": order_id, "qty": qty, "price": price, **kwargs}
```

Implement `IBExecutionClient` with:
- `connect(host, port, client_id)`
- `submit_mkt_order(symbol, qty, side, client_order_id)`
- `wait_for_updates(timeout_seconds)` returning buffer

**Step 4: Run tests**

Run: `pytest backend/tests/test_ib_execution.py::test_execution_event_buffer_records_updates -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_execution.py backend/tests/test_ib_execution.py
git commit -m "feat: add ib execution buffer and client"
```

---

### Task 4: Wire execution into trade_executor

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_executor_execution.py`

**Step 1: Write failing test**

```python
from app.services.trade_executor import _apply_order_status

def test_apply_order_status_updates_fields():
    order = {"status": "NEW"}
    _apply_order_status(order, status="Submitted")
    assert order["status"] == "SUBMITTED"
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_executor_execution.py::test_apply_order_status_updates_fields -q`
Expected: FAIL (function missing)

**Step 3: Implement minimal execution wiring**
- Add helper `_apply_order_status` and `_record_fill`.
- In `execute_trade_run`, after orders are created, call `IBExecutionClient` to submit orders (MKT only) and collect updates for a timeout window.
- Update `trade_orders` fields and insert `trade_fills`.
- Set run status: `success` if all FILLED, `partial` if any PARTIAL, `failed` if any REJECTED/timeout.

**Step 4: Run tests**

Run: `pytest backend/tests/test_trade_executor_execution.py::test_apply_order_status_updates_fields -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_executor_execution.py
git commit -m "feat: wire ib execution into trade executor"
```

---

### Task 5: Expose orders + fills endpoints

**Files:**
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_routes.py`

**Step 1: Write failing test**

```python
def test_trade_run_orders_endpoint(client):
    resp = client.get("/api/trade/runs/1/orders")
    assert resp.status_code in {200, 404}
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_routes.py::test_trade_run_orders_endpoint -q`
Expected: FAIL (route missing)

**Step 3: Implement endpoint**
- Add `GET /api/trade/runs/{id}/orders` returning order list with nested fills.

**Step 4: Run tests**

Run: `pytest backend/tests/test_trade_routes.py::test_trade_run_orders_endpoint -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/routes/trade.py backend/app/schemas.py backend/tests/test_trade_routes.py
git commit -m "feat: add trade run orders endpoint"
```

---

### Task 6: Final verification

**Step 1: Run focused tests**

Run: `pytest backend/tests/test_trade_models.py backend/tests/test_ib_execution.py backend/tests/test_trade_executor_execution.py backend/tests/test_trade_routes.py -q`
Expected: PASS

**Step 2: Summarize results**
- Note any warnings or skipped tests.

**Step 3: Commit (if any changes after fixes)**

```bash
git add -A
git commit -m "test: verify ib trade execution flow"
```

---

## Execution Handoff
Plan complete and saved to `docs/plans/2026-01-23-ib-trade-execution-implementation-plan.md`.

Two execution options:

1. **Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration
2. **Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?
