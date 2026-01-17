# 盘中风控（Phase 3.2）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现盘中风险管理：监控损益/回撤/异常事件，触发阈值后进入“停止交易、保留持仓”保护状态，并在 UI 可见。

**Architecture:** 新增 `trade_guard_state` 表与服务层 `trade_guard`，通过周期评估与下单前检查触发风控；估值优先 IB，异常时降级本地快照；LiveTrade UI 展示风控状态与估值来源。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL, React + Vite, pytest。

---

### Task 1: 建模与数据库补丁

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
# backend/app/models.py (新增模型)
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
-- 变更说明: 新增盘中风控状态表 trade_guard_state
-- 影响范围: 交易系统盘中风控
-- 回滚指引: DROP TABLE trade_guard_state;
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

### Task 2: 服务层风控引擎（估值 + 阈值评估）

**Files:**
- Create: `backend/app/services/trade_guard.py`
- Modify: `backend/app/services/ib_market.py` (仅在必要时复用工具函数)
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
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_guard.py
# 关键函数：
# - get_or_create_guard_state(session, project_id, mode, trade_date)
# - evaluate_intraday_guard(session, project_id, mode, risk_params, price_map=None)
# - record_guard_event(session, project_id, mode, event="order_failure"|"market_data_error")
```

最小实现要求：
- 使用 `fetch_market_snapshots` 获取报价；若报价错误或时间戳过期（`valuation_stale_seconds`），读取 `data/ib/stream/<symbol>.json` 作为本地 fallback。
- 计算 equity：`cash_available`（若无则 0） + 持仓市值。
- `day_start_equity` 首次设置；`equity_peak` 取最大；更新 `last_equity`。
- 触发 `max_daily_loss` / `max_intraday_drawdown` / `max_order_failures` / `max_market_data_errors` / `max_risk_triggers` → `status=halted`。
- 返回字典包含 `status`, `reason`, `valuation_source`。

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_service.py::test_guard_triggers_daily_loss -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_guard.py backend/tests/test_trade_guard_service.py
git commit -m "feat: add intraday risk guard service"
```

---

### Task 3: API 路由与 Schema

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
class TradeGuardStateOut(BaseModel):
    id: int
    project_id: int
    trade_date: date
    mode: str
    status: str
    halt_reason: dict | None
    risk_triggers: int
    order_failures: int
    market_data_errors: int
    day_start_equity: float | None
    equity_peak: float | None
    last_equity: float | None
    last_valuation_ts: datetime | None
    valuation_source: str | None
    cooldown_until: datetime | None
    created_at: datetime
    updated_at: datetime

class TradeGuardEvaluateRequest(BaseModel):
    project_id: int
    mode: str = "paper"
    risk_params: dict | None = None

class TradeGuardEvaluateOut(BaseModel):
    state: TradeGuardStateOut
    result: dict
```

```python
# backend/app/routes/trade.py
@router.get("/guard", response_model=TradeGuardStateOut)
def get_trade_guard_state(project_id: int, mode: str = "paper"):
    # get_or_create_guard_state(...)

@router.post("/guard/evaluate", response_model=TradeGuardEvaluateOut)
def evaluate_guard(payload: TradeGuardEvaluateRequest):
    # 调用 evaluate_intraday_guard
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

### Task 4: 交易执行集成（下单前阻断 + 事件计数）

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/trade_orders.py` (如需事件记录)
- Test: `backend/tests/test_trade_guard_execution.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_guard_execution.py
from app.services.trade_executor import execute_trade_run

def test_execute_blocked_when_guard_halted(session, trade_run):
    # 先创建 guard_state 并置为 halted
    result = execute_trade_run(trade_run.id, dry_run=True)
    assert result.status == "blocked"
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_guard_execution.py::test_execute_blocked_when_guard_halted -q`
Expected: FAIL (still executes)

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_executor.py
# 在风险检查前：
# - 调用 get_guard_state
# - 若 halted -> block
# 订单拒绝/行情缺失时：调用 record_guard_event(...)
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

### Task 5: LiveTrade UI 展示盘中风控状态

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/styles.css` (如需新增样式)

**Step 1: Write the failing test (UI snapshot or e2e stub)**

```ts
// 可使用最小 Playwright 脚本或本地手工验证
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run build`
Expected: PASS (但无风控展示)

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
// - 拉取 /api/trade/guard?project_id=...&mode=...
// - 展示 status / equity / drawdown / valuation_source / halt_reason
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/src/styles.css
git commit -m "feat: show intraday risk guard on live trade page"
```

---

### Task 6: 回归测试

**Files:**
- Test: `backend/tests/*`

**Step 1: Run all backend tests**

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
