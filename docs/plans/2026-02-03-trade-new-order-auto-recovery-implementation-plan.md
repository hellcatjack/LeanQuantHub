# NEW 订单自动处置 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为实盘监控中的 NEW 状态订单提供超时自动撤单 + 条件重下的自动处置能力，并可审计。

**Architecture:** 后端新增自动处置服务，按配置扫描超时 NEW 订单，执行本地撤单并视条件重下；暴露手动触发接口，记录 audit_logs。

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, Pytest。

**约束说明（重要）**
- 项目禁止使用 git worktree；所有改动在主工作区完成。

---

### Task 1: 数据库补丁（trade_settings 自动处置配置）

**Files:**
- Create: `deploy/mysql/patches/20260203_trade_settings_auto_recovery.sql`

**Step 1: Write the patch**

```sql
-- 变更说明: 为 trade_settings 增加 auto_recovery JSON 配置
-- 影响范围: trade_settings
-- 回滚指引: ALTER TABLE trade_settings DROP COLUMN auto_recovery;

ALTER TABLE trade_settings
  ADD COLUMN IF NOT EXISTS auto_recovery JSON NULL AFTER execution_data_source;

-- 可选: 记录到 schema_migrations (若存在)
INSERT INTO schema_migrations (version, applied_at)
SELECT '20260203_trade_settings_auto_recovery', NOW()
WHERE EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'
)
AND NOT EXISTS (
  SELECT 1 FROM schema_migrations WHERE version = '20260203_trade_settings_auto_recovery'
);
```

**Step 2: Manual check**
Run: `mysql -e "DESC trade_settings;"`
Expected: `auto_recovery` 列存在

**Step 3: Commit**
```bash
git add deploy/mysql/patches/20260203_trade_settings_auto_recovery.sql
git commit -m "chore(db): add trade settings auto recovery config"
```

---

### Task 2: 模型与 Schema 扩展

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/trade.py`
- Test: `backend/tests/test_trade_settings_auto_recovery.py`

**Step 1: Write failing test**

```python
# backend/tests/test_trade_settings_auto_recovery.py
from app.models import Base, TradeSettings
from app.schemas import TradeSettingsOut
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_settings_includes_auto_recovery_defaults():
    session = _make_session()
    try:
        row = TradeSettings(risk_defaults={}, execution_data_source="ib", auto_recovery=None)
        session.add(row)
        session.commit()
        out = TradeSettingsOut.model_validate(row, from_attributes=True)
        assert out.auto_recovery is not None
        assert out.auto_recovery.get("new_timeout_seconds") == 45
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_trade_settings_auto_recovery.py -v`
Expected: FAIL (auto_recovery missing)

**Step 3: Minimal implementation**
- `models.py`: add `auto_recovery` JSON column to `TradeSettings`
- `schemas.py`: add `TradeAutoRecoveryConfig` + `auto_recovery` in `TradeSettingsOut/Update`
- `routes/trade.py`: get/update 默认 auto_recovery（fallback to defaults）

Example schema snippet:

```python
class TradeAutoRecoveryConfig(BaseModel):
    new_timeout_seconds: int = 45
    max_auto_retries: int = 1
    max_price_deviation_pct: float = 1.5
    allow_replace_outside_rth: bool = False

class TradeSettingsOut(BaseModel):
    auto_recovery: dict | None = None
```

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_trade_settings_auto_recovery.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/models.py backend/app/schemas.py backend/app/routes/trade.py backend/tests/test_trade_settings_auto_recovery.py
git commit -m "feat: add trade auto recovery config"
```

---

### Task 3: 自动处置服务（超时撤单 + 重下）

**Files:**
- Create: `backend/app/services/trade_order_recovery.py`
- Modify: `backend/app/services/trade_orders.py` (必要时提供 helper)
- Test: `backend/tests/test_trade_order_recovery.py`

**Step 1: Write failing tests**

```python
# backend/tests/test_trade_order_recovery.py
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder, TradeSettings
from app.services import trade_order_recovery


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_recovery_cancels_and_replaces_new_order(monkeypatch):
    session = _make_session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="ib", auto_recovery={"new_timeout_seconds": 1}))
        session.commit()
        order = TradeOrder(
            client_order_id="c1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="NEW",
            filled_quantity=0.0,
            created_at=datetime.utcnow() - timedelta(seconds=10),
        )
        session.add(order)
        session.commit()

        monkeypatch.setattr(trade_order_recovery, "_probe_ib_socket", lambda *a, **k: True, raising=False)
        result = trade_order_recovery.run_auto_recovery(session, now=datetime.utcnow())

        assert result["cancelled"] == 1
        assert result["replaced"] == 1
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_trade_order_recovery.py -v`
Expected: FAIL (service missing)

**Step 3: Minimal implementation**
Create `trade_order_recovery.py` with:
- `resolve_auto_recovery_settings(session)`
- `_eligible_new_orders(session, cutoff, limit)`
- `run_auto_recovery(session, now=None, limit=200)` returning counts
- For each eligible order: update status to `CANCELED` (local), then create replacement order with params `{"auto_recovery": {...}}`
- Skip if `ib_order_id/ib_perm_id` 已存在或 `filled_quantity > 0`
- Skip if `_probe_ib_socket` 失败或 guard halted
- 写 `audit_logs`

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_trade_order_recovery.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/trade_order_recovery.py backend/tests/test_trade_order_recovery.py
git commit -m "feat: add NEW order auto recovery service"
```

---

### Task 4: API 入口（手动触发）

**Files:**
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_trade_order_auto_recovery_route.py`

**Step 1: Write failing test**

```python
# backend/tests/test_trade_order_auto_recovery_route.py
from fastapi.testclient import TestClient
from app.main import app

def test_auto_recovery_route_returns_counts():
    client = TestClient(app)
    res = client.post("/api/trade/orders/auto-recover")
    assert res.status_code == 200
    assert "cancelled" in res.json()
```

**Step 2: Run test to verify it fails**
Run: `cd backend && pytest tests/test_trade_order_auto_recovery_route.py -v`
Expected: FAIL (route missing)

**Step 3: Minimal implementation**
- 新增 `TradeAutoRecoveryOut` schema
- `POST /api/trade/orders/auto-recover` 调用 `run_auto_recovery`

**Step 4: Run test to verify it passes**
Run: `cd backend && pytest tests/test_trade_order_auto_recovery_route.py -v`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/routes/trade.py backend/app/schemas.py backend/tests/test_trade_order_auto_recovery_route.py
git commit -m "feat: add manual auto recovery trigger"
```

---

### Task 5: 端到端自测（手动）

**Step 1: 造一条 NEW 订单**
Run: `curl -X POST http://localhost:8021/api/trade/orders -H 'Content-Type: application/json' -d '{"client_order_id":"auto-test-1","symbol":"AAPL","side":"BUY","quantity":1,"order_type":"MKT"}'`
Expected: 订单状态 NEW

**Step 2: 手动触发恢复**
Run: `curl -X POST http://localhost:8021/api/trade/orders/auto-recover`
Expected: 返回 cancelled/replaced 计数

**Step 3: 查询订单列表**
Run: `curl -s http://localhost:8021/api/trade/orders | head`
Expected: 原订单状态 CANCELED，新订单出现

---

### Task 6: 收尾

**Step 1: 全量核心测试（最小集）**
Run: `cd backend && pytest tests/test_trade_settings_auto_recovery.py tests/test_trade_order_recovery.py tests/test_trade_order_auto_recovery_route.py -v`
Expected: PASS

**Step 2: 提交与推送**
```bash
git status -sb
git push origin main
```

