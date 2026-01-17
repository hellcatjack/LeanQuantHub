# 预交易风控（Phase 3.1）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现“全局默认 + 单次覆盖”的预交易风控，阻断违规下单并记录审计。

**Architecture:** 在后端新增 `trade_settings` 保存全局风控默认值；执行时合并 `risk_overrides` → `risk_effective`，由风险引擎评估并在失败时阻断交易。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL，pytest。

### Task 1: 新增 trade_settings 模型与接口

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/trade.py`
- Create: `deploy/mysql/patches/20260117_trade_settings.sql`
- Test: `backend/tests/test_trade_settings_api.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient


def test_trade_settings_defaults_roundtrip(client: TestClient):
    resp = client.get("/api/trade/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert "risk_defaults" in payload

    updated = {"risk_defaults": {"max_order_notional": 1000}}
    resp2 = client.post("/api/trade/settings", json=updated)
    assert resp2.status_code == 200
    assert resp2.json()["risk_defaults"]["max_order_notional"] == 1000
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_settings_api.py::test_trade_settings_defaults_roundtrip -q`
Expected: FAIL (endpoint/model not found)

**Step 3: Write minimal implementation**

- Add `TradeSettings` model with `risk_defaults` JSON and timestamps
- Add schema `TradeSettingsOut` and `TradeSettingsUpdate`
- Add routes:
  - `GET /api/trade/settings`
  - `POST /api/trade/settings`
- Add DB patch `deploy/mysql/patches/20260117_trade_settings.sql` (idempotent)

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_settings_api.py::test_trade_settings_defaults_roundtrip -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/models.py backend/app/schemas.py backend/app/routes/trade.py deploy/mysql/patches/20260117_trade_settings.sql backend/tests/test_trade_settings_api.py
git commit -m "feat: add trade settings defaults for risk"
```

---

### Task 2: 风险引擎扩展（max_total_notional / max_symbols / min_cash_buffer_ratio）

**Files:**
- Modify: `backend/app/services/trade_risk_engine.py`
- Test: `backend/tests/test_trade_risk_engine.py`

**Step 1: Write the failing tests**

```python
from app.services.trade_risk_engine import evaluate_orders


def test_risk_max_total_notional_blocks():
    ok, blocked, reasons = evaluate_orders(
        [{"symbol": "A", "quantity": 10, "price": 10}, {"symbol": "B", "quantity": 10, "price": 10}],
        max_order_notional=None,
        max_position_ratio=None,
        portfolio_value=1000,
        max_total_notional=150,
        max_symbols=None,
        cash_available=None,
        min_cash_buffer_ratio=None,
    )
    assert ok is False
    assert any(r.startswith("max_total_notional") for r in reasons)


def test_risk_max_symbols_blocks():
    ok, blocked, reasons = evaluate_orders(
        [{"symbol": "A", "quantity": 1, "price": 10}, {"symbol": "B", "quantity": 1, "price": 10}],
        max_order_notional=None,
        max_position_ratio=None,
        portfolio_value=1000,
        max_total_notional=None,
        max_symbols=1,
        cash_available=None,
        min_cash_buffer_ratio=None,
    )
    assert ok is False
    assert any(r.startswith("max_symbols") for r in reasons)


def test_risk_min_cash_buffer_ratio_blocks():
    ok, blocked, reasons = evaluate_orders(
        [{"symbol": "A", "quantity": 50, "price": 10}],
        max_order_notional=None,
        max_position_ratio=None,
        portfolio_value=1000,
        max_total_notional=None,
        max_symbols=None,
        cash_available=100,
        min_cash_buffer_ratio=0.2,
    )
    assert ok is False
    assert any(r.startswith("min_cash_buffer_ratio") for r in reasons)
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_risk_engine.py::test_risk_max_total_notional_blocks -q`
Expected: FAIL (signature/logic missing)

**Step 3: Write minimal implementation**

- Extend `evaluate_orders` signature and logic:
  - `max_total_notional`
  - `max_symbols`
  - `cash_available` + `min_cash_buffer_ratio`

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_risk_engine.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_risk_engine.py backend/tests/test_trade_risk_engine.py
git commit -m "feat: extend trade risk engine checks"
```

---

### Task 3: 交易执行整合（risk_defaults + risk_overrides → risk_effective）

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_execution_builder.py`

**Step 1: Write the failing test**

```python
from app.services.trade_executor import _merge_risk_params


def test_merge_risk_params_override():
    defaults = {"max_order_notional": 1000, "max_symbols": 5}
    overrides = {"max_order_notional": 500}
    merged = _merge_risk_params(defaults, overrides)
    assert merged["max_order_notional"] == 500
    assert merged["max_symbols"] == 5
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_execution_builder.py::test_merge_risk_params_override -q`
Expected: FAIL (helper missing)

**Step 3: Write minimal implementation**

- Add helper `_merge_risk_params`
- In `execute_trade_run`, load `TradeSettings.risk_defaults`
- Merge with `risk_overrides` from `run.params`
- Store `risk_effective` to `run.params`
- Pass new fields to `evaluate_orders`
- If risk blocked, set status/message/params and return early

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_trade_execution_builder.py::test_merge_risk_params_override -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/tests/test_trade_execution_builder.py
git commit -m "feat: apply trade risk defaults and overrides"
```

---

### Task 4: 文档与校验

**Files:**
- Modify: `docs/plans/2026-01-17-trade-pre-risk-design.md`
- Modify: `docs/plans/2026-01-17-trade-pre-risk-design.en.md`

**Step 1: Update docs**

补充 `trade_settings` 实际落库与接口路径说明。

**Step 2: Run full tests**

Run: `/app/stocklean/.venv/bin/pytest -q`
Expected: PASS (warnings OK)

**Step 3: Commit**

```bash
git add docs/plans/2026-01-17-trade-pre-risk-design.md docs/plans/2026-01-17-trade-pre-risk-design.en.md
git commit -m "docs: document trade risk defaults" 
```

