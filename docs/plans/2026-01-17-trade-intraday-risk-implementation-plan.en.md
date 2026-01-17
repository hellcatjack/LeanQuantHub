# Intraday Risk Guard (Phase 3.2) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement intraday risk management: monitor PnL/drawdown/errors, halt new trading on breach while keeping positions, and expose status in UI.

**Architecture:** Add `trade_guard_state` table + `trade_guard` service. Guard evaluates thresholds using IB data with local fallback; enforce guard pre-order and via periodic evaluation. LiveTrade UI shows guard status and valuation source.

**Tech Stack:** FastAPI + SQLAlchemy + MySQL, React + Vite, pytest.

---

### Task 1: Model + DB Patch

**Files:**
- Modify: `backend/app/models.py`
- Create: `deploy/mysql/patches/20260117_trade_guard_state.sql`
- Test: `backend/tests/test_trade_guard_state.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_guard_state.py
from app.models import TradeGuardState

def test_trade_guard_state_model_fields():
    state = TradeGuardState(project_id=1, trade_date="2026-01-17", mode="paper")
    assert state.status == "active"
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_state.py::test_trade_guard_state_model_fields -q`
Expected: FAIL (ImportError / missing model)

**Step 3: Write minimal implementation**

```python
# backend/app/models.py (new model)
class TradeGuardState(Base):
    __tablename__ = "trade_guard_state"
    __table_args__ = (
        UniqueConstraint("project_id", "trade_date", "mode", name="uq_trade_guard_state"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="paper")
    status: Mapped[str] = mapped_column(String(16), default="active")
    halt_reason: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_triggers: Mapped[int] = mapped_column(Integer, default=0)
    order_failures: Mapped[int] = mapped_column(Integer, default=0)
    market_data_errors: Mapped[int] = mapped_column(Integer, default=0)
    day_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_valuation_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valuation_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

```sql
-- deploy/mysql/patches/20260117_trade_guard_state.sql
-- Change: add intraday risk guard table
-- Rollback: DROP TABLE trade_guard_state;
CREATE TABLE IF NOT EXISTS trade_guard_state (
  id INT PRIMARY KEY AUTO_INCREMENT,
  project_id INT NOT NULL,
  trade_date DATE NOT NULL,
  mode VARCHAR(16) NOT NULL DEFAULT 'paper',
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  halt_reason JSON NULL,
  risk_triggers INT NOT NULL DEFAULT 0,
  order_failures INT NOT NULL DEFAULT 0,
  market_data_errors INT NOT NULL DEFAULT 0,
  day_start_equity DOUBLE NULL,
  equity_peak DOUBLE NULL,
  last_equity DOUBLE NULL,
  last_valuation_ts DATETIME NULL,
  valuation_source VARCHAR(32) NULL,
  cooldown_until DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_trade_guard_state (project_id, trade_date, mode)
);
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_state.py::test_trade_guard_state_model_fields -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/models.py deploy/mysql/patches/20260117_trade_guard_state.sql backend/tests/test_trade_guard_state.py
git commit -m "feat: add trade guard state model"
```

---

### Task 2: Guard Service (valuation + thresholds)

**Files:**
- Create: `backend/app/services/trade_guard.py`
- Modify: `backend/app/services/ib_market.py` (only if helper needed)
- Test: `backend/tests/test_trade_guard_service.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_guard_service.py
from app.services.trade_guard import evaluate_intraday_guard

def test_guard_triggers_daily_loss(session, trade_settings, trade_run_with_fills):
    result = evaluate_intraday_guard(session, project_id=1, mode="paper", risk_params={
        "max_daily_loss": -0.01,
        "portfolio_value": 100000,
    })
    assert result["status"] == "halted"
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_service.py::test_guard_triggers_daily_loss -q`
Expected: FAIL (module missing)

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_guard.py
# Key functions:
# - get_or_create_guard_state(...)
# - evaluate_intraday_guard(...)
# - record_guard_event(...)
```

Minimal requirements:
- Use `fetch_market_snapshots` for prices; if stale or missing (`valuation_stale_seconds`), read local `data/ib/stream/<symbol>.json`.
- Equity = cash_available (default 0) + sum(qty * price).
- Set day_start_equity once; update equity_peak; persist last_equity.
- Thresholds: max_daily_loss / max_intraday_drawdown / max_order_failures / max_market_data_errors / max_risk_triggers → status=halted.
- Return dict with status/reason/valuation_source.

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_service.py::test_guard_triggers_daily_loss -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_guard.py backend/tests/test_trade_guard_service.py
git commit -m "feat: add intraday risk guard service"
```

---

### Task 3: API + Schemas

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_trade_guard_api.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_guard_api.py
from fastapi.testclient import TestClient
from app.main import app

def test_guard_state_api():
    client = TestClient(app)
    res = client.get("/api/trade/guard", params={"project_id": 1, "mode": "paper"})
    assert res.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_api.py::test_guard_state_api -q`
Expected: FAIL (404)

**Step 3: Write minimal implementation**

```python
# backend/app/schemas.py
class TradeGuardStateOut(BaseModel): ...
class TradeGuardEvaluateRequest(BaseModel): ...
class TradeGuardEvaluateOut(BaseModel): ...
```

```python
# backend/app/routes/trade.py
@router.get("/guard", response_model=TradeGuardStateOut)
@router.post("/guard/evaluate", response_model=TradeGuardEvaluateOut)
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_api.py::test_guard_state_api -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/trade.py backend/tests/test_trade_guard_api.py
git commit -m "feat: add trade guard api"
```

---

### Task 4: Execution Integration (block + event counters)

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/trade_orders.py` (if needed)
- Test: `backend/tests/test_trade_guard_execution.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_guard_execution.py
from app.services.trade_executor import execute_trade_run

def test_execute_blocked_when_guard_halted(session, trade_run):
    result = execute_trade_run(trade_run.id, dry_run=True)
    assert result.status == "blocked"
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_execution.py::test_execute_blocked_when_guard_halted -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_executor.py
# - Check guard state before risk engine; block if halted
# - On price unavailable / rejected, record event counters
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_execution.py::test_execute_blocked_when_guard_halted -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_guard_execution.py
git commit -m "feat: integrate guard check into trade execution"
```

---

### Task 5: LiveTrade UI Guard Panel

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css` (if needed)

**Step 1: Run build (baseline)**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 2: Implement guard panel**

```tsx
// LiveTradePage.tsx
// - fetch /api/trade/guard
// - display status/equity/drawdown/valuation_source/reason
```

**Step 3: Build**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/src/styles.css
git commit -m "feat: show intraday risk guard on live trade page"
```

---

### Task 6: Regression Verification

**Step 1: Run backend tests**

Run: `/app/stocklean/.venv/bin/pytest -q`
Expected: PASS

**Step 2: Build frontend**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 3: Commit**

```bash
git add -A
git commit -m "test: verify intraday risk guard"
```
