# Lean 回测与实盘统一执行 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将回测与实盘执行统一收敛到 Lean 执行内核，后端仅下发权重与参数，订单生成与约束由 Lean 负责，实现可审计一致性。

**Architecture:** 后端输出两类文件：`order_intent`（权重/符号）与 `execution_params`（约束/费用/现金规则），Lean 回测/实盘读取同一输入生成 PortfolioTargets 与订单事件；后端不再编译订单，仅创建可审计的意图占位订单并接收 Lean 事件写回。

**Tech Stack:** FastAPI + SQLAlchemy（backend）、Lean Algorithm（`algorithms/lean_trend_rotation.py`）、JSON 参数文件、Pytest。

---

### Task 1: 新增执行参数文件写入与测试

**Files:**
- Create: `backend/app/services/lean_execution_params.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_lean_execution_params.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
from app.services.lean_execution_params import write_execution_params


def test_write_execution_params_writes_json(tmp_path: Path):
    path = write_execution_params(
        output_dir=tmp_path,
        run_id=123,
        params={"min_qty": 1, "lot_size": 5, "cash_buffer_ratio": 0.1},
    )
    data = Path(path).read_text(encoding="utf-8")
    assert "min_qty" in data
    assert "lot_size" in data
    assert "cash_buffer_ratio" in data
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_lean_execution_params.py::test_write_execution_params_writes_json -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`.

**Step 3: Write minimal implementation**

```python
# backend/app/services/lean_execution_params.py
from __future__ import annotations

import json
from pathlib import Path


def write_execution_params(*, output_dir: Path, run_id: int, params: dict) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"execution_params_run_{run_id}.json"
    payload = dict(params)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_lean_execution_params.py::test_write_execution_params_writes_json -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/lean_execution_params.py backend/tests/test_lean_execution_params.py
git commit -m "feat: add lean execution params writer"
```

---

### Task 2: 为决策快照创建意图占位订单（不再编译数量）

**Files:**
- Modify: `backend/app/services/trade_order_builder.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_intent_orders.py`

**Step 1: Write the failing test**

```python
from app.services.trade_order_builder import build_intent_orders


def test_build_intent_orders_uses_weight_sign():
    items = [
        {"symbol": "AAPL", "weight": 0.02},
        {"symbol": "MSFT", "weight": -0.01},
    ]
    orders = build_intent_orders(items)
    assert orders[0]["side"] == "BUY"
    assert orders[1]["side"] == "SELL"
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_intent_orders.py::test_build_intent_orders_uses_weight_sign -v`
Expected: FAIL with `ImportError` or `AttributeError`.

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_order_builder.py

def build_intent_orders(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            weight = float(item.get("weight"))
        except (TypeError, ValueError):
            continue
        side = "BUY" if weight >= 0 else "SELL"
        orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": 0,
                "order_type": "MKT",
                "limit_price": None,
            }
        )
    return orders
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_intent_orders.py::test_build_intent_orders_uses_weight_sign -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/trade_order_builder.py backend/tests/test_trade_intent_orders.py
git commit -m "feat: add intent order drafts from snapshot weights"
```

---

### Task 3: 交易执行改为“权重+参数下发 + 意图占位订单”

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/lean_execution.py`
- Test: `backend/tests/test_trade_executor_lean_intent.py`

**Step 1: Write the failing test**

```python
from app.services.trade_executor import _should_skip_order_build


def test_should_skip_order_build_for_lean():
    assert _should_skip_order_build("lean") is True
    assert _should_skip_order_build("non_lean") is False
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_executor_lean_intent.py::test_should_skip_order_build_for_lean -v`
Expected: FAIL with `ImportError` or `AttributeError`.

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_executor.py

def _should_skip_order_build(execution_source: str | None) -> bool:
    return str(execution_source or "").strip().lower() == "lean"
```

Then update main flow (excerpt):

```python
# inside execute_trade_run (decision snapshot branch)
from app.services.trade_order_builder import build_intent_orders
from app.services.lean_execution_params import write_execution_params

execution_source = (settings_row.execution_data_source if settings_row else "lean") or "lean"
skip_build = _should_skip_order_build(execution_source)

intent_path = write_order_intent(...)
params["order_intent_path"] = intent_path

# write execution params file for Lean
execution_params = {
    "min_qty": int(params.get("min_qty") or 1),
    "lot_size": int(params.get("lot_size") or 1),
    "cash_buffer_ratio": float(params.get("cash_buffer_ratio") or 0.0),
    "fee_bps": float(params.get("fee_bps") or 0.0),
    "slippage_open_bps": float(params.get("slippage_open_bps") or 0.0),
    "slippage_close_bps": float(params.get("slippage_close_bps") or 0.0),
    "risk_overrides": params.get("risk_overrides") or {},
}
params["execution_params_path"] = write_execution_params(
    output_dir=ARTIFACT_ROOT / "order_intents",
    run_id=run.id,
    params=execution_params,
)

if skip_build:
    draft_orders = build_intent_orders(items)
else:
    draft_orders = build_orders(...)
```

And ensure `build_execution_config` includes param path:

```python
# backend/app/services/lean_execution.py
payload["execution-intent-path"] = intent_path
if params_path:
    payload["execution-params-path"] = params_path
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_executor_lean_intent.py::test_should_skip_order_build_for_lean -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/app/services/lean_execution.py backend/tests/test_trade_executor_lean_intent.py
git commit -m "feat: trade executor uses lean intent + params when execution source is lean"
```

---

### Task 4: 回测入口对齐执行参数映射

**Files:**
- Modify: `backend/app/services/lean_runner.py`
- Test: `backend/tests/test_lean_runner_params.py`

**Step 1: Write the failing test**

```python
from app.services.lean_runner import _build_execution_params_payload


def test_build_execution_params_payload_defaults():
    payload = _build_execution_params_payload({})
    assert payload["min_qty"] == 1
    assert payload["lot_size"] == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_lean_runner_params.py::test_build_execution_params_payload_defaults -v`
Expected: FAIL with `ImportError` or `AttributeError`.

**Step 3: Write minimal implementation**

```python
# backend/app/services/lean_runner.py

def _build_execution_params_payload(params: dict) -> dict:
    return {
        "min_qty": int(params.get("min_qty") or 1),
        "lot_size": int(params.get("lot_size") or 1),
        "cash_buffer_ratio": float(params.get("cash_buffer_ratio") or 0.0),
        "fee_bps": float(params.get("fee_bps") or 0.0),
        "slippage_open_bps": float(params.get("slippage_open_bps") or 0.0),
        "slippage_close_bps": float(params.get("slippage_close_bps") or 0.0),
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_lean_runner_params.py::test_build_execution_params_payload_defaults -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/lean_runner.py backend/tests/test_lean_runner_params.py
git commit -m "feat: align lean runner execution params payload"
```

---

### Task 5: Lean 算法读取统一参数并执行约束

**Files:**
- Modify: `algorithms/lean_trend_rotation.py`
- Test: `algorithms/tests/test_lean_execution_params.py` (若无测试目录则创建 `algorithms/tests/__init__.py`)

**Step 1: Write the failing test**

```python
from algorithms.lean_trend_rotation import _apply_execution_constraints


def test_apply_execution_constraints_min_qty():
    qty = _apply_execution_constraints(raw_qty=0.2, lot_size=1, min_qty=1)
    assert qty == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest algorithms/tests/test_lean_execution_params.py::test_apply_execution_constraints_min_qty -v`
Expected: FAIL with `ImportError` or `AttributeError`.

**Step 3: Write minimal implementation**

```python
# algorithms/lean_trend_rotation.py

def _apply_execution_constraints(*, raw_qty: float, lot_size: int, min_qty: int) -> int:
    lot = max(1, int(lot_size))
    min_qty_value = max(1, int(min_qty))
    if min_qty_value % lot != 0:
        min_qty_value = int(math.ceil(min_qty_value / lot)) * lot
    qty = int(math.ceil(raw_qty / lot)) * lot
    if qty < min_qty_value:
        qty = min_qty_value
    return max(0, qty)
```

**Step 4: Run test to verify it passes**

Run: `pytest algorithms/tests/test_lean_execution_params.py::test_apply_execution_constraints_min_qty -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add algorithms/lean_trend_rotation.py algorithms/tests/test_lean_execution_params.py
git commit -m "feat: lean algorithm applies unified execution constraints"
```

---

### Task 6: 一致性回归与文档更新

**Files:**
- Modify: `docs/plans/2026-02-06-lean-unified-execution-design.md` (追加实现进度说明)
- Test: `backend/tests/test_trade_executor_lean_intent.py` (增加回归用例)

**Step 1: Write the failing test**

```python
from app.services.trade_order_builder import build_intent_orders


def test_intent_orders_dont_require_price():
    orders = build_intent_orders([{"symbol": "AAPL", "weight": 0.02}])
    assert orders[0]["quantity"] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_executor_lean_intent.py::test_intent_orders_dont_require_price -v`
Expected: FAIL if quantity not zero or builder not used.

**Step 3: Write minimal implementation**

```python
# ensure build_intent_orders returns quantity=0 consistently
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_executor_lean_intent.py::test_intent_orders_dont_require_price -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/plans/2026-02-06-lean-unified-execution-design.md backend/tests/test_trade_executor_lean_intent.py
git commit -m "docs: note lean unified execution progress"
```

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-02-06-lean-unified-execution-implementation-plan.md`.

Two execution options:

1. Subagent-Driven (this session) — I dispatch a fresh subagent per task, review between tasks.
2. Parallel Session (separate) — Open a new session and use `superpowers:executing-plans` with checkpoints.

Which approach?
