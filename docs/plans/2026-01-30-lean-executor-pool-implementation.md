# Lean 执行器常驻池 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 paper/live 各提供 10 个常驻 Lean 执行器池，Leader 独占 bridge 输出，Worker 只下单，稳定 <1s 下单延迟。

**Architecture:** 后端进程内托管池管理器，维护实例状态与心跳；Leader 输出固定桥接目录；Worker 仅下单；新增 API 与 UI 子页面。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL, React + Vite + TypeScript, Pytest, Playwright

---

### Task 1: 新增池配置项（TDD）

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_lean_pool_settings.py`

**Step 1: Write the failing test**

```python
from app.core import config

def test_lean_pool_settings_present():
    assert hasattr(config.settings, "lean_pool_size")
    assert hasattr(config.settings, "lean_pool_max_active_connections")
    assert hasattr(config.settings, "lean_pool_heartbeat_ttl_seconds")
    assert hasattr(config.settings, "lean_pool_leader_restart_limit")
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_lean_pool_settings.py -v`
Expected: FAIL (missing attrs)

**Step 3: Write minimal implementation**

Add in `config.py`:
```python
    lean_pool_size: int = 10
    lean_pool_max_active_connections: int = 10
    lean_pool_heartbeat_ttl_seconds: int = 20
    lean_pool_leader_restart_limit: int = 3
```

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_lean_pool_settings.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_lean_pool_settings.py
git commit -m "feat: add lean executor pool settings"
```

---

### Task 2: 新增数据表与迁移（TDD）

**Files:**
- Create: `deploy/mysql/patches/20260130_lean_executor_pool.sql`
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_lean_executor_models.py`

**Step 1: Write the failing test**

```python
from app import models

def test_lean_executor_models_exist():
    assert hasattr(models, "LeanExecutorPool")
    assert hasattr(models, "LeanExecutorEvent")
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_lean_executor_models.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add SQL patch with:
- `lean_executor_pool` table
- `lean_executor_events` table
- migration note, rollback hints, idempotent guard

Add models in `models.py` with fields from design.

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_lean_executor_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add deploy/mysql/patches/20260130_lean_executor_pool.sql backend/app/models.py backend/tests/test_lean_executor_models.py
git commit -m "feat: add lean executor pool tables"
```

---

### Task 3: 池管理器服务（TDD）

**Files:**
- Create: `backend/app/services/lean_executor_pool.py`
- Test: `backend/tests/test_lean_executor_pool.py`

**Step 1: Write failing tests**

```python
from app.services import lean_executor_pool

def test_pool_selects_single_leader():
    pool = lean_executor_pool.LeanExecutorPoolManager(mode="paper", size=3)
    roles = [inst.role for inst in pool.instances]
    assert roles.count("leader") == 1


def test_pool_marks_dead_pid_stale():
    inst = lean_executor_pool.ExecutorInstance(pid=999999, role="worker")
    assert inst.is_alive() is False
```

**Step 2: Run test to verify fail**

Run: `cd backend && pytest tests/test_lean_executor_pool.py -v`
Expected: FAIL

**Step 3: Implement minimal class + helpers**

- `ExecutorInstance` dataclass
- `LeanExecutorPoolManager` with init/leader selection
- `_pid_alive` utility

**Step 4: Run tests pass**

Run: `cd backend && pytest tests/test_lean_executor_pool.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/lean_executor_pool.py backend/tests/test_lean_executor_pool.py
git commit -m "feat: add lean executor pool manager"
```

---

### Task 4: Leader 独占 bridge 输出目录（TDD）

**Files:**
- Modify: `backend/app/services/lean_execution.py`
- Test: `backend/tests/test_lean_execution_config.py`

**Step 1: Write failing test**

```python
def test_execution_config_leader_output_dir(monkeypatch):
    from app.services import lean_execution
    cfg = lean_execution.build_execution_config(
        intent_path="/tmp/intent.json",
        brokerage="InteractiveBrokersBrokerage",
        project_id=1,
        mode="paper",
        client_id=1234,
        lean_bridge_output_dir="/data/share/stock/data/lean_bridge",
    )
    assert cfg["lean-bridge-output-dir"].endswith("/lean_bridge")
```

**Step 2: Run test to verify fail**

Run: `cd backend && pytest tests/test_lean_execution_config.py::test_execution_config_leader_output_dir -v`
Expected: FAIL if output dir not respected

**Step 3: Minimal implementation**

Ensure `build_execution_config` uses supplied `lean_bridge_output_dir` unchanged.

**Step 4: Run test pass**

Run: `cd backend && pytest tests/test_lean_execution_config.py::test_execution_config_leader_output_dir -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/lean_execution.py backend/tests/test_lean_execution_config.py
git commit -m "fix: honor leader bridge output dir"
```

---

### Task 5: 下单路由到 Worker（TDD）

**Files:**
- Modify: `backend/app/services/trade_direct_order.py`
- Modify: `backend/app/services/ib_client_id_pool.py`
- Test: `backend/tests/test_trade_direct_order_pool.py`

**Step 1: Write failing test**

```python
from app.services import trade_direct_order

def test_direct_order_uses_worker_client_id(monkeypatch, session):
    # mock pool to return worker
    monkeypatch.setattr(trade_direct_order, "_select_worker", lambda *_: 2001)
    payload = {"mode":"paper","symbol":"AAPL","side":"BUY","quantity":1,"order_type":"MKT"}
    out = trade_direct_order.submit_direct_order(session, payload)
    assert out.execution_status == "submitted_lean"
```

**Step 2: Run test to verify fail**

Run: `cd backend && pytest tests/test_trade_direct_order_pool.py -v`
Expected: FAIL

**Step 3: Implement minimal routing helper**

- add `_select_worker` helper
- ensure it picks healthy worker client_id

**Step 4: Run test pass**

Run: `cd backend && pytest tests/test_trade_direct_order_pool.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_direct_order.py backend/app/services/ib_client_id_pool.py backend/tests/test_trade_direct_order_pool.py
git commit -m "feat: route direct orders to worker pool"
```

---

### Task 6: 新增 API 接口（TDD）

**Files:**
- Modify: `backend/app/routes/brokerage.py`
- Create: `backend/tests/test_lean_pool_api.py`

**Step 1: Write failing test**

```python
from fastapi.testclient import TestClient
from app.main import app

def test_pool_status_endpoint():
    client = TestClient(app)
    res = client.get("/api/lean/pool/status?mode=paper")
    assert res.status_code == 200
```

**Step 2: Run fail**

Run: `cd backend && pytest tests/test_lean_pool_api.py -v`
Expected: FAIL

**Step 3: Implement minimal endpoints**

Add handlers in `brokerage.py`.

**Step 4: Run pass**

Run: `cd backend && pytest tests/test_lean_pool_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/routes/brokerage.py backend/tests/test_lean_pool_api.py
git commit -m "feat: add lean pool api endpoints"
```

---

### Task 7: 前端 Bridge Pool 子页面（TDD）

**Files:**
- Create: `frontend/src/pages/LeanBridgePoolPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/tests/lean-bridge-pool.spec.ts`

**Step 1: Write failing test**

```ts
import { test, expect } from "@playwright/test";

test("bridge pool page shows leader", async ({ page }) => {
  await page.goto("/live-trade/bridge-pool");
  await expect(page.getByText(/Leader/i)).toBeVisible();
});
```

**Step 2: Run fail**

Run: `cd frontend && npx playwright test tests/lean-bridge-pool.spec.ts -g "leader" --reporter=line`
Expected: FAIL

**Step 3: Implement minimal page**

Add page + route, display table.

**Step 4: Run pass**

Run: `cd frontend && npx playwright test tests/lean-bridge-pool.spec.ts -g "leader" --reporter=line`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LeanBridgePoolPage.tsx frontend/src/App.tsx frontend/src/i18n.tsx frontend/tests/lean-bridge-pool.spec.ts
git commit -m "feat: add lean bridge pool page"
```

---

### Task 8: 端到端验证 + 构建

**Run:**
- `cd backend && pytest -v`
- `cd frontend && npm run test:e2e -- --project=chromium --grep "bridge pool"`
- `cd frontend && npm run build`

**Commit:**
```bash
git add -A
git commit -m "chore: verify lean executor pool"
```

---

**完成后：**使用 `superpowers:finishing-a-development-branch` 完成收尾（如合并/推送）。
