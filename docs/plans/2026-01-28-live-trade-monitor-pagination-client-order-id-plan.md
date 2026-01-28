# 实盘监控分页与手工 client_order_id 唯一后缀 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为实盘监控订单列表加入分页（默认 50，支持 50/100/200）并让手工 client_order_id 自动追加唯一 suffix。

**Architecture:** 后端为 `/api/trade/orders` 增加 `X-Total-Count` 响应头；新增序列表生成唯一 suffix，手工 `client_order_id` 自动追加；前端订单表只显示全局订单并接入 `PaginationBar`。

**Tech Stack:** FastAPI, SQLAlchemy, MySQL, React, Vite, Vitest。

---

### Task 1: 数据库序列表迁移（TDD 前置准备）

**Files:**
- Create: `deploy/mysql/patches/20260128_trade_order_client_id_seq.sql`

**Step 1: Write migration script**

```sql
-- 变更说明：新增 trade_order_client_id_seq 用于生成唯一 client_order_id suffix
-- 影响范围：新增表，不影响现有数据
-- 回滚指引：DROP TABLE IF EXISTS trade_order_client_id_seq;

CREATE TABLE IF NOT EXISTS trade_order_client_id_seq (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Step 2: Commit**

```bash
git add deploy/mysql/patches/20260128_trade_order_client_id_seq.sql
git commit -m "chore(db): add client order id sequence table"
```

---

### Task 2: 后端 suffix 生成工具与测试（TDD）

**Files:**
- Create: `backend/tests/test_trade_order_client_id_suffix.py`
- Modify: `backend/app/services/trade_orders.py`

**Step 1: Write the failing test**

```python
from app.services.trade_orders import build_manual_client_order_id

def test_build_manual_client_order_id_appends_suffix():
    assert build_manual_client_order_id("manual-abc", 35) == "manual-abc-z"
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_order_client_id_suffix.py -v`
Expected: FAIL (function not found)

**Step 3: Write minimal implementation**

```python
def _base36(value: int) -> str:
    # convert positive int to base36
    ...

def build_manual_client_order_id(base: str, seq_id: int) -> str:
    suffix = _base36(seq_id)
    return f"{base}-{suffix}"
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_order_client_id_suffix.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_orders.py backend/tests/test_trade_order_client_id_suffix.py
git commit -m "feat: add manual client order id suffix builder"
```

---

### Task 3: 后端生成 suffix 并写入 params（TDD）

**Files:**
- Modify: `backend/app/services/trade_orders.py`
- Modify: `backend/app/services/trade_direct_order.py`
- Modify: `backend/app/services/trade_executor.py`
- Create: `backend/tests/test_trade_order_manual_id.py`

**Step 1: Write failing tests**

```python
import re
from app.services.trade_orders import apply_manual_client_order_id

def test_apply_manual_client_order_id_suffixes_and_preserves_original():
    payload = {"client_order_id": "manual-test", "params": {"source": "direct"}}
    updated = apply_manual_client_order_id(payload, seq_id=123)
    assert updated["client_order_id"].startswith("manual-test-")
    assert updated["params"]["original_client_order_id"] == "manual-test"
```

**Step 2: Run test (should fail)**

Run: `pytest backend/tests/test_trade_order_manual_id.py -v`
Expected: FAIL

**Step 3: Implement apply + DB seq fetch**

- 在 `trade_orders.py` 增加：
  - `get_client_order_id_seq(session)`：插入序列表并返回 seq_id
  - `apply_manual_client_order_id(payload, seq_id)`：追加 suffix、处理超长、记录原始值
  - 判断“手工来源”并在 `create_trade_order` 内调用
- 在 `trade_direct_order.submit_direct_order` 调用 `create_trade_order` 前：标记 `params.source = "direct"`（已有）
- 在 `trade_executor` 自动下单路径：设置 `params.client_order_id_auto = True`，避免被改写

**Step 4: Run test**

Run: `pytest backend/tests/test_trade_order_manual_id.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_orders.py backend/app/services/trade_executor.py backend/tests/test_trade_order_manual_id.py
git commit -m "feat: suffix manual client_order_id with sequence"
```

---

### Task 4: `/api/trade/orders` 添加 `X-Total-Count`（TDD）

**Files:**
- Modify: `backend/app/routes/trade.py`
- Create: `backend/tests/test_trade_orders_pagination.py`

**Step 1: Write failing test**

```python
from fastapi.testclient import TestClient
from app.main import app

def test_orders_total_count_header():
    client = TestClient(app)
    resp = client.get("/api/trade/orders?limit=1&offset=0")
    assert "X-Total-Count" in resp.headers
```

**Step 2: Run test**

Run: `pytest backend/tests/test_trade_orders_pagination.py -v`
Expected: FAIL

**Step 3: Implement header**

- 在 `list_trade_orders` 中计算 total（count）并写入 `Response` header

**Step 4: Run test**

Run: `pytest backend/tests/test_trade_orders_pagination.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/routes/trade.py backend/tests/test_trade_orders_pagination.py
git commit -m "feat: add X-Total-Count to trade orders"
```

---

### Task 5: 前端实盘监控分页与全局订单（TDD）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.ts`
- (Optional) Modify: `frontend/src/components/PaginationBar.tsx`

**Step 1: Write failing test**

```ts
it("loads orders with default page size 50", () => {
  // mock api.get to expect limit=50
});
```

**Step 2: Run test**

Run: `cd frontend && npm test -- src/pages/LiveTradePage.test.ts`
Expected: FAIL

**Step 3: Implement pagination state**

- 新增 state：`ordersPage`, `ordersPageSize`, `ordersTotal`
- `loadTradeActivity` 请求 `/api/trade/orders` 使用 `limit=ordersPageSize`, `offset=(ordersPage-1)*ordersPageSize`
- 从响应头读取 `X-Total-Count`
- 订单表渲染 `tradeOrders`（不再用 runDetail.orders）
- 插入 `PaginationBar`（pageSizeOptions 为 50/100/200）

**Step 4: Run tests**

Run: `cd frontend && npm test`
Expected: PASS

**Step 5: Build & Restart**

```bash
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```

**Step 6: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/pages/LiveTradePage.test.ts
# plus PaginationBar if changed
git commit -m "feat: add live trade monitor pagination"
```

---

### Task 6: 验证

- 批量手工下单（相同 base）不冲突，client_order_id 自动追加 suffix。
- 实盘监控分页可切换 50/100/200，页码显示正确。
- 选中批次时订单表仍显示全局订单。

