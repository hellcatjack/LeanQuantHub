# 直发 IB/TWS 订单接口 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增“直发 IB/TWS”接口，Paper/Live 可用（Live 需 token），手动下单能真正触发 Lean 执行并到达 TWS。

**Architecture:** 后端新增直发路由与服务，创建 `TradeOrder`（`run_id=null`）并生成直发 intent 文件，通过 Lean 执行配置触发 IB；Lean 算法支持负数量（SELL）。前端手动下单改为调用直发接口并透传 token。

**Tech Stack:** FastAPI + SQLAlchemy + Lean (C#) + React + Vite

> 注意：当前 `pytest` 在未设置 `PYTHONPATH` 的情况下会报 `ModuleNotFoundError: app`。本计划中的测试命令统一使用 `PYTHONPATH=.`。

---

### Task 1: 直发 intent 构建函数（TDD）

**Files:**
- Create: `backend/app/services/trade_direct_intent.py`
- Test: `backend/tests/test_trade_direct_intent.py`

**Step 1: Write the failing test**

```python
from app.services.trade_direct_intent import build_direct_intent_items


def test_build_direct_intent_sell_negative():
    items = build_direct_intent_items(order_id=10, symbol="AAPL", side="SELL", quantity=2)
    assert items == [
        {"order_intent_id": "direct:10", "symbol": "AAPL", "quantity": -2.0}
    ]


def test_build_direct_intent_buy_positive():
    items = build_direct_intent_items(order_id=11, symbol="NVDA", side="BUY", quantity=1)
    assert items == [
        {"order_intent_id": "direct:11", "symbol": "NVDA", "quantity": 1.0}
    ]
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest -q tests/test_trade_direct_intent.py::test_build_direct_intent_sell_negative`
Expected: FAIL (ImportError or function not found)

**Step 3: Write minimal implementation**

```python
from __future__ import annotations


def build_direct_intent_items(*, order_id: int, symbol: str, side: str, quantity: float) -> list[dict]:
    signed = float(quantity)
    if str(side).strip().upper() == "SELL":
        signed = -abs(signed)
    else:
        signed = abs(signed)
    return [
        {
            "order_intent_id": f"direct:{order_id}",
            "symbol": str(symbol).strip().upper(),
            "quantity": signed,
        }
    ]
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest -q tests/test_trade_direct_intent.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_direct_intent.py backend/tests/test_trade_direct_intent.py
git commit -m "feat: add direct order intent builder"
```

---

### Task 2: Lean 执行算法支持 SELL（负数量）

**Files:**
- Modify: `/app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs`
- Modify: `/app/stocklean/Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs`

**Step 1: Write the failing test**

```csharp
[Test]
public void BuildRequests_AllowsNegativeQuantity()
{
    var items = new List<LeanBridgeExecutionAlgorithm.IntentItem>
    {
        new LeanBridgeExecutionAlgorithm.IntentItem { Symbol = "AAPL", Quantity = -1m, Weight = 0m }
    };
    var requests = LeanBridgeExecutionAlgorithm.BuildRequests(items);
    Assert.That(requests.Count, Is.EqualTo(1));
    Assert.That(requests[0].Quantity, Is.EqualTo(-1m));
    Assert.That(requests[0].UseQuantity, Is.True);
}
```

**Step 2: Run test to verify it fails**

Run: `dotnet test /app/stocklean/Lean_git/Tests/Algorithm/Algorithm.Tests.csproj -c Release --filter FullyQualifiedName~LeanBridgeExecutionAlgorithmTests.BuildRequests_AllowsNegativeQuantity`
Expected: FAIL

**Step 3: Write minimal implementation**

在 `BuildRequests` 中将 `item.Quantity > 0` 改为 `item.Quantity != 0`，保留原有 weight 逻辑。

**Step 4: Run test to verify it passes**

Run: 同 Step 2
Expected: PASS

**Step 5: Commit**

```bash
git add /app/stocklean/Lean_git/Algorithm.CSharp/LeanBridgeExecutionAlgorithm.cs \
  /app/stocklean/Lean_git/Tests/Algorithm/LeanBridgeExecutionAlgorithmTests.cs
git commit -m "feat: allow negative quantity in lean bridge execution"
```

---

### Task 3: 后端直发接口与执行服务（TDD）

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/services/trade_direct_order.py`
- Modify: `backend/app/routes/trade.py`
- Create: `backend/tests/test_trade_direct_order_validation.py`

**Step 1: Write the failing test**

```python
from app.services.trade_direct_order import validate_direct_order_payload


def test_validate_direct_order_rejects_lmt():
    payload = {
        "mode": "paper",
        "order_type": "LMT",
        "side": "BUY",
        "quantity": 1,
        "symbol": "AAPL",
    }
    assert validate_direct_order_payload(payload) == (False, "order_type_invalid")
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest -q tests/test_trade_direct_order_validation.py::test_validate_direct_order_rejects_lmt`
Expected: FAIL

**Step 3: Write minimal implementation**

- `schemas.py` 新增 `TradeDirectOrderRequest` / `TradeDirectOrderOut`。
- `trade_direct_order.py` 提供：
  - `validate_direct_order_payload(payload) -> (ok, reason)`
  - `submit_direct_order(session, payload) -> TradeDirectOrderOut`
  - 生成 intent：调用 `build_direct_intent_items`，写入 `artifacts/order_intents/order_intent_direct_{order_id}.json`
  - 生成执行配置并 `launch_execution()`
  - 写入探针文件 `artifacts/lean_execution/direct_order_{order_id}.json`
  - 记录 audit：`trade_order.direct_submit`
- `trade.py` 新增 `POST /api/trade/orders/direct`，使用新 schema 与 service。

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest -q tests/test_trade_direct_order_validation.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/trade.py \
  backend/app/services/trade_direct_order.py backend/tests/test_trade_direct_order_validation.py
git commit -m "feat: add direct order API and validation"
```

---

### Task 4: 前端调用直发接口 + 文案

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Write the failing test**

（如无合适前端测试框架，记录为手工验证步骤。）

**Step 2: Implement minimal changes**

- `submitPositionOrders` 调用 `/api/trade/orders/direct`。
- Payload 补充：`project_id`（优先 `selectedProjectId`，否则 `latestTradeRun.project_id`），`mode`（`ibSettings?.mode || ibSettingsForm.mode`），`live_confirm_token`（当 mode=live 时传 `executeForm.live_confirm_token`）。
- 无 project 时显示错误（新增 `trade.directOrderProjectRequired`）。

**Step 3: Build & restart (required)**

Run:
- `cd frontend && npm run build`
- `systemctl --user restart stocklean-frontend`

Expected: build success，前端可访问。

**Step 4: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx
git commit -m "feat: send manual orders via direct API"
```

---

### Task 5: 验证与回归

**Step 1: 后端单元测试**

Run: `PYTHONPATH=. pytest -q tests/test_trade_direct_intent.py tests/test_trade_direct_order_validation.py`
Expected: PASS

**Step 2: 手工验证（最小路径）**

1) 在“实盘交易”页面选择项目。
2) 选择一条持仓点“SELL 1”。
3) Paper 模式应直接提交；Live 模式需输入口令并成功提交。
4) 观察 TWS 是否收到订单。

**Step 3: Commit（若有补丁）**

```bash
git add -A
git commit -m "chore: finalize direct order flow"
```

