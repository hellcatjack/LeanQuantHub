# Lean Bridge Payload 回写 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 Lean 下单时写入 payload Tag，并在 execution_events.jsonl 中回传，后端精确回写/补齐订单与成交。

**Architecture:** 后端在 execution intent 中生成 `order_intent_id`；LeanBridgeExecutionAlgorithm 读取 intent 并将 `order_intent_id` 写入订单 Tag；LeanBridgeResultHandler 将 Tag 原样输出到事件；后端用 Tag=order_intent_id 精确定位或补齐订单（回查 intent 获取详情）。

**Tech Stack:** C# (Lean), Python (FastAPI backend), Pytest, MySQL

### Task 1: 后端生成 order_intent_id（RED）

**Files:**
- Modify: `backend/app/services/trade_execution.py` (或生成 execution intent 的实际文件)
- Test: `backend/tests/test_trade_execution_builder.py` (或新增测试)

**Step 1: Write the failing test**

```python
def test_order_intent_has_stable_intent_id(db_session):
    # 构造最小 trade_run/intents（使用现有 builder）
    # 期望每条 intent 包含 order_intent_id 且为唯一字符串
    intents = build_execution_intents(..., session=db_session)
    assert all(\"order_intent_id\" in item for item in intents)
    assert len({item[\"order_intent_id\"] for item in intents}) == len(intents)
```

**Step 2: Run test to verify it fails**

Run: `cd /app/stocklean/.worktrees/lean-bridge-payload && PYTHONPATH=backend pytest backend/tests/test_trade_execution_builder.py::test_order_intent_has_stable_intent_id -q`
Expected: FAIL

**Step 3: Write minimal implementation**

- 在 execution intent 生成逻辑处新增 `order_intent_id`（例如 `oi_{snapshot_id}_{index}` 或 `oi_{run_id}_{index}`）\n

**Step 4: Run test to verify it passes**

Run: `cd /app/stocklean/.worktrees/lean-bridge-payload && PYTHONPATH=backend pytest backend/tests/test_trade_execution_builder.py::test_order_intent_has_stable_intent_id -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_execution.py backend/tests/test_trade_execution_builder.py
git commit -m "feat: add order_intent_id to execution intents"
```

### Task 2: 后端事件解析最小测试（RED）

**Files:**
- Create: `backend/tests/test_lean_execution_events.py`
- Modify: `backend/app/services/lean_execution.py`

**Step 1: Write the failing test**

```python
import json
from datetime import datetime, timezone

import pytest

from app.models import TradeOrder
from app.services.lean_execution import apply_execution_events


def test_apply_execution_events_creates_and_fills_missing_order(db_session):
    events = [
        {
            "order_id": 9,
            "symbol": "AMAT",
            "status": "Filled",
            "filled": 3.0,
            "fill_price": 334.15,
            "direction": "Buy",
            "time": "2026-01-27T15:25:46.9105632Z",
            "tag": "oi_33_12"
        }
    ]

    apply_execution_events(events, session=db_session)

    order = db_session.query(TradeOrder).filter(TradeOrder.client_order_id == "oi_33_12").one()
    assert order.status == "FILLED"
    assert float(order.filled_quantity) == 3.0
    assert float(order.avg_fill_price) == 334.15
    assert order.ib_order_id == 9
```

**Step 2: Run test to verify it fails**

Run: `cd /app/stocklean/.worktrees/lean-bridge-payload && PYTHONPATH=backend pytest backend/tests/test_lean_execution_events.py::test_apply_execution_events_creates_and_fills_missing_order -q`
Expected: FAIL (apply_execution_events missing / signature mismatch)

**Step 3: Write minimal implementation**

Implement `apply_execution_events(events, session)` in `backend/app/services/lean_execution.py`:
- Tag 仅为 `order_intent_id`
- Find TradeOrder by `client_order_id` = intent_id
- If missing: 通过 intent 文件回查（execution-intent-path）获取 symbol/side/quantity/order_type，再创建 TradeOrder
- Apply fill using `apply_fill_to_order`, set `ib_order_id` to order_id

**Step 4: Run test to verify it passes**

Run: `cd /app/stocklean/.worktrees/lean-bridge-payload && PYTHONPATH=backend pytest backend/tests/test_lean_execution_events.py::test_apply_execution_events_creates_and_fills_missing_order -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_lean_execution_events.py backend/app/services/lean_execution.py
git commit -m "feat: apply lean execution events with payload tag"
```

### Task 3: 后端错误处理测试（RED）

**Files:**
- Modify: `backend/tests/test_lean_execution_events.py`
- Modify: `backend/app/services/lean_execution.py`

**Step 1: Write the failing test**

```python
def test_apply_execution_events_rejects_invalid_tag(db_session):
    events = [
        {"order_id": 1, "symbol": "AMD", "status": "Filled", "filled": 1, "fill_price": 10,
         "direction": "Buy", "time": "2026-01-27T00:00:00Z", "tag": "not-json"}
    ]

    apply_execution_events(events, session=db_session)

    order = db_session.query(TradeOrder).filter(TradeOrder.ib_order_id == 1).first()
    assert order is None
```

**Step 2: Run test to verify it fails**

Run: `cd /app/stocklean/.worktrees/lean-bridge-payload && PYTHONPATH=backend pytest backend/tests/test_lean_execution_events.py::test_apply_execution_events_rejects_invalid_tag -q`
Expected: FAIL

**Step 3: Write minimal implementation**

- When tag invalid or missing required fields, skip creation and log warning (no order created).

**Step 4: Run test to verify it passes**

Run: `cd /app/stocklean/.worktrees/lean-bridge-payload && PYTHONPATH=backend pytest backend/tests/test_lean_execution_events.py::test_apply_execution_events_rejects_invalid_tag -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_lean_execution_events.py backend/app/services/lean_execution.py
git commit -m "test: skip invalid lean payload tags"
```

### Task 4: Lean 下单 Tag 写入（C#）

**Files:**
- Modify: `/app/stocklean/.worktrees/lean-bridge-payload/Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs`

**Step 1: Write the failing test**

创建简单本地验证脚本/注释断言（Lean 未有现成测试框架）：
- 在算法运行日志中输出最终 tag 字符串与长度
- 期望字段齐全且长度<=180

**Step 2: Run to verify failure**

Run: `dotnet run --project /app/stocklean/.worktrees/lean-bridge-payload/Lean_git/Launcher --config /app/stocklean/.worktrees/lean-bridge-payload/configs/lean_live_interactive_paper.json`
Expected: 日志缺少 tag

**Step 3: Minimal implementation**

- 在读取 execution-intent 时生成/读取 `order_intent_id`
- 生成紧凑 JSON tag（字段白名单）
- 写入 OrderTag

**Step 4: Run to verify pass**

Expected: 日志输出 tag 且长度<=180

**Step 5: Commit**

```bash
git add Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs
git commit -m "feat: add payload tag to lean orders"
```

### Task 5: Lean ResultHandler 回传 tag

**Files:**
- Modify: `/app/stocklean/.worktrees/lean-bridge-payload/Lean_git/Engine/Results/LeanBridgeResultHandler.cs`

**Step 1: Write the failing test**

运行同上配置，确认 execution_events.jsonl 未包含 tag 字段。

**Step 2: Run to verify failure**

Expected: events 无 tag 字段

**Step 3: Minimal implementation**

- 将 OrderTag 写入事件 JSON 中 `tag` 字段

**Step 4: Run to verify pass**

Expected: events 含 tag 字段

**Step 5: Commit**

```bash
git add Lean_git/Engine/Results/LeanBridgeResultHandler.cs
git commit -m "feat: include order tag in lean bridge events"
```

### Task 6: 回写验证与数据修复

**Files:**
- Modify: `backend/app/services/lean_execution.py`

**Step 1: Run replay script**

编写脚本调用 `apply_execution_events` 对当前 `execution_events.jsonl` 回放。

**Step 2: Verify DB**

SQL:
```sql
select status, count(*) from trade_orders where run_id=25 group by status;
```
Expected: 全部 FILLED

**Step 3: Commit**

```bash
git add backend/app/services/lean_execution.py
git commit -m "fix: replay lean execution events"
```
