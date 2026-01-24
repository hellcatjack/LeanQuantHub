# Phase 2 Trade Execution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan.

**Goal:** 完成 Paper + Live 共用的订单执行闭环（MKT、全并发），支持 Live UI 二次确认与幂等执行。

**Architecture:** 复用现有 `trade_runs`/`trade_orders`/`trade_executor`，补齐 DB 迁移、幂等校验、Live 口令校验，并实现最小可用 IB 下单客户端与执行结果回写。

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, React/Vite, IB API

---

### Task 1: 数据库迁移（trade_runs/orders/fills + trade_settings.execution_data_source）

**Files:**
- Create: `deploy/mysql/patches/20260124_trade_execution_tables.sql`

**Step 1: Write the migration file**
```sql
-- 变更说明：补齐实盘交易相关表 + trade_settings.execution_data_source
-- 影响范围：trade_runs / trade_orders / trade_fills / trade_settings
-- 回滚指引：删除新增表/列（仅在确认无数据时执行）

-- trade_runs
CREATE TABLE IF NOT EXISTS trade_runs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  project_id BIGINT NOT NULL,
  decision_snapshot_id BIGINT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  params JSON NULL,
  message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  ended_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_trade_runs_project_id (project_id),
  INDEX idx_trade_runs_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- trade_orders
CREATE TABLE IF NOT EXISTS trade_orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_id BIGINT NULL,
  client_order_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  side VARCHAR(8) NOT NULL,
  quantity DOUBLE NOT NULL,
  order_type VARCHAR(16) NOT NULL DEFAULT 'MKT',
  limit_price DOUBLE NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'NEW',
  filled_quantity DOUBLE NOT NULL DEFAULT 0,
  avg_fill_price DOUBLE NULL,
  ib_order_id BIGINT NULL,
  ib_perm_id BIGINT NULL,
  last_status_ts DATETIME NULL,
  rejected_reason TEXT NULL,
  params JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_trade_order_client_id (client_order_id),
  INDEX idx_trade_orders_run_id (run_id),
  INDEX idx_trade_orders_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- trade_fills
CREATE TABLE IF NOT EXISTS trade_fills (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  order_id BIGINT NOT NULL,
  fill_quantity DOUBLE NOT NULL,
  fill_price DOUBLE NOT NULL,
  commission DOUBLE NULL,
  fill_time DATETIME NULL,
  exec_id VARCHAR(64) NULL,
  currency VARCHAR(16) NULL,
  exchange VARCHAR(32) NULL,
  raw_payload JSON NULL,
  params JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_trade_fills_order_id (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- trade_settings.execution_data_source
SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'trade_settings'
    AND COLUMN_NAME = 'execution_data_source'
);
SET @sql := IF(@exists = 0,
  'ALTER TABLE trade_settings ADD COLUMN execution_data_source VARCHAR(16) NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
```

**Step 2: Sanity check (no DB apply here)**
Run: `rg -n "trade_execution_tables" deploy/mysql/patches/20260124_trade_execution_tables.sql`
Expected: file present

**Step 3: Commit**
```bash
git add deploy/mysql/patches/20260124_trade_execution_tables.sql
git commit -m "db: add trade execution tables and settings column"
```

---

### Task 2: Live 口令 + 运行批次幂等（API 层）

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_trade_run_create_idempotent.py`

**Step 1: Write failing tests**
```python
# backend/tests/test_trade_run_create_idempotent.py
from contextlib import contextmanager
from pathlib import Path
import sys
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.routes.trade as trade_routes
from app.schemas import TradeRunCreate, TradeRunExecuteRequest
from app.models import Base, Project, DecisionSnapshot, TradeRun

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_run_idempotent(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path="/tmp/x.csv")
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "check_market_health", lambda *_a, **_k: {"status": "ok"})

        payload = TradeRunCreate(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            orders=[],
            require_market_health=False,
        )
        first = trade_routes.create_trade_run(payload)
        second = trade_routes.create_trade_run(payload)
        assert first.id == second.id
    finally:
        session.close()


def test_live_confirm_required(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path="/tmp/x.csv")
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "check_market_health", lambda *_a, **_k: {"status": "ok"})

        payload = TradeRunCreate(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="live",
            orders=[],
            require_market_health=False,
        )
        try:
            trade_routes.create_trade_run(payload)
        except Exception as exc:
            assert "live_confirm_required" in str(exc)
    finally:
        session.close()


def test_execute_requires_live_confirm(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(project_id=project.id, decision_snapshot_id=1, mode="live", status="queued", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = TradeRunExecuteRequest(dry_run=True, force=False, live_confirm_token=None)
        try:
            trade_routes.execute_trade_run_route(run.id, payload)
        except Exception as exc:
            assert "live_confirm_required" in str(exc)
    finally:
        session.close()
```

**Step 2: Run tests to see failures**
Run: `pytest backend/tests/test_trade_run_create_idempotent.py -q`
Expected: FAIL (missing live confirm + idempotency)

**Step 3: Implement schema & route changes**
```python
# schemas.py
class TradeRunCreate(BaseModel):
    ...
    live_confirm_token: str | None = None

class TradeRunExecuteRequest(BaseModel):
    dry_run: bool = False
    force: bool = False
    live_confirm_token: str | None = None
```

```python
# routes/trade.py (create_trade_run)
if payload.mode.lower() == "live" and (payload.live_confirm_token or "").strip().upper() != "LIVE":
    raise HTTPException(status_code=403, detail="live_confirm_required")

# idempotency: same project_id + decision_snapshot_id + mode + trade_date (today)
existing = (
    session.query(TradeRun)
    .filter(
        TradeRun.project_id == payload.project_id,
        TradeRun.decision_snapshot_id == snapshot_id,
        TradeRun.mode == payload.mode,
        TradeRun.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
    )
    .order_by(TradeRun.created_at.desc())
    .first()
)
if existing:
    out = TradeRunOut.model_validate(existing, from_attributes=True)
    out.orders_created = 0
    return out

# orders optional: if none, keep queued; execution will build from snapshot
```

```python
# routes/trade.py (execute_trade_run_route)
if run.mode == "live" and (payload.live_confirm_token or "").strip().upper() != "LIVE":
    raise HTTPException(status_code=403, detail="live_confirm_required")
```

**Step 4: Re-run tests**
Run: `pytest backend/tests/test_trade_run_create_idempotent.py -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/schemas.py backend/app/routes/trade.py backend/tests/test_trade_run_create_idempotent.py
git commit -m "feat: enforce live confirm and trade run idempotency"
```

---

### Task 3: 订单构建器改为四舍五入

**Files:**
- Modify: `backend/app/services/trade_order_builder.py`
- Test: `backend/tests/test_trade_execution_builder.py`

**Step 1: Write failing test**
```python
# add to backend/tests/test_trade_execution_builder.py
from app.services.trade_order_builder import build_orders

def test_build_orders_rounding():
    items = [{"symbol": "SPY", "weight": 0.1}]
    price_map = {"SPY": 95}  # 0.1 * 1000 / 95 = 1.05 => rounds to 1
    orders = build_orders(items, price_map=price_map, portfolio_value=1000)
    assert orders[0]["quantity"] == 1
```

**Step 2: Run test to see failure**
Run: `pytest backend/tests/test_trade_execution_builder.py::test_build_orders_rounding -q`
Expected: FAIL (flooring)

**Step 3: Update builder**
```python
# trade_order_builder.py
raw_qty = target / price
lot = max(1, int(lot_size))
qty = int(round(raw_qty / lot)) * lot
if qty <= 0:
    continue
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_execution_builder.py::test_build_orders_rounding -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_order_builder.py backend/tests/test_trade_execution_builder.py
git commit -m "feat: round order quantities in builder"
```

---

### Task 4: 实现最小可用 IBExecutionClient（MKT）

**Files:**
- Modify: `backend/app/services/ib_execution.py`
- Test: `backend/tests/test_ib_execution_client.py`

**Step 1: Write failing test (mock EClient)**
```python
# backend/tests/test_ib_execution_client.py
from app.services.ib_execution import IBExecutionClient

def test_ib_execution_client_returns_events(monkeypatch):
    client = IBExecutionClient("127.0.0.1", 7497, 101)
    monkeypatch.setattr(client, "_submit_orders", lambda orders: ["OK"])
    events = client.submit_orders([object()])
    assert events
```

**Step 2: Run test to see failure**
Run: `pytest backend/tests/test_ib_execution_client.py -q`
Expected: FAIL (stub)

**Step 3: Implement minimal client**
```python
# ib_execution.py
# - 使用 ibapi EClient/EWrapper
# - connect + nextValidId
# - placeOrder (MKT)
# - orderStatus/execDetails 记录
# - timeout 后标记 SUBMITTED
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_ib_execution_client.py -q`
Expected: PASS (mocked path)

**Step 5: Commit**
```bash
git add backend/app/services/ib_execution.py backend/tests/test_ib_execution_client.py
git commit -m "feat: add minimal IB execution client"
```

---

### Task 5: 执行器整合 IB 提交与状态回写

**Files:**
- Modify: `backend/app/services/ib_order_executor.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_executor_ib.py`

**Step 1: Write failing test**
```python
# extend backend/tests/test_trade_executor_ib.py

def test_execute_trade_run_updates_ib_status(monkeypatch, session, run_with_orders):
    def _submit(session, orders, *, price_map=None):
        class E: pass
        e = E(); e.order_id = orders[0].id; e.status = "SUBMITTED"; e.exec_id=None; e.filled=0; e.avg_price=None
        return [e]
    monkeypatch.setattr("app.services.ib_order_executor.IBOrderExecutor.submit_orders", _submit)
    result = trade_executor.execute_trade_run(run_with_orders.id, dry_run=False)
    assert result.status in {"partial", "done"}
```

**Step 2: Run test to see failure**
Run: `pytest backend/tests/test_trade_executor_ib.py::test_execute_trade_run_updates_ib_status -q`
Expected: FAIL

**Step 3: Implement IB path**
```python
# trade_executor.py
# - 当 api_mode==ib 时，使用 IBOrderExecutor.submit_orders
# - 根据返回事件更新 TradeOrder 状态/填充 TradeFill
# - run.status 按 filled/rejected/cancelled 计算
```

**Step 4: Run test to verify it passes**
Run: `pytest backend/tests/test_trade_executor_ib.py::test_execute_trade_run_updates_ib_status -q`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/ib_order_executor.py backend/app/services/trade_executor.py backend/tests/test_trade_executor_ib.py
git commit -m "feat: wire IB execution into trade executor"
```

---

### Task 6: LiveTrade UI 添加执行入口（含 LIVE 口令）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Add UI form (run_id + live_confirm_token)**
```tsx
// LiveTradePage.tsx: add a small form section
// Fields: run_id, live_confirm_token
// POST /api/trade/runs/{id}/execute
```

**Step 2: Run frontend test/build**
Run: `cd frontend && npm run build`
Expected: build success

**Step 3: Commit**
```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx
git commit -m "feat: add live execute form"
```

---

### Task 7: 更新 TODO 状态

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Mark Phase 2 items as done (if all above merged)**
```markdown
- [x] 2.1 订单状态机 ...
- [x] 2.2 订单拆分与下单规则 ...
```

**Step 2: Commit**
```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: update trade phase 2 status"
```
