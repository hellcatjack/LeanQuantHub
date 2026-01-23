# IB 实盘交易连接状态聚合面板 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 增加 `/api/ib/status/overview` 聚合接口并在 LiveTrade 页面展示连接状态面板，统一轮询与错误处理。

**Architecture:** 后端提供聚合状态接口，复用现有配置/状态/流文件/订单/审计数据源，前端新增面板卡片组与轮询刷新，不触发自动探测。

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic；React + Vite。

---

### Task 1: 后端聚合接口 Schema 与 Service

**Files:**
- Create: `backend/app/services/ib_status_overview.py`
- Modify: `backend/app/schemas.py`

**Step 1: Write the failing test**

Create `backend/tests/test_ib_status_overview.py` (new) with minimal failing test:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_ib_status_overview_shape():
    resp = client.get("/api/ib/status/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "connection" in data
    assert "config" in data
    assert "stream" in data
    assert "snapshot_cache" in data
    assert "orders" in data
    assert "alerts" in data
    assert "refreshed_at" in data
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_status_overview.py::test_ib_status_overview_shape -q`
Expected: FAIL (404 或字段缺失)

**Step 3: Write minimal implementation**

Add Pydantic schema in `backend/app/schemas.py`:

```python
class IBStatusOverviewOut(BaseModel):
    connection: dict
    config: dict
    stream: dict
    snapshot_cache: dict
    orders: dict
    alerts: dict
    partial: bool = False
    errors: list[str] = []
    refreshed_at: datetime
```

Add service in `backend/app/services/ib_status_overview.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
from app.services.ib_settings import get_or_create_ib_settings, get_or_create_ib_state
from app.services import ib_stream
from app.models import TradeOrder, TradeFill, AuditLog

MASK_KEYS = {"account_id"}

# build_ib_status_overview(session) -> dict
# 1) 读取 settings/state/stream
# 2) 读取 stream 目录最新 json 的 mtime 作为 snapshot_cache
# 3) 读取最新 TradeOrder/TradeFill
# 4) 读取最新 AuditLog (action 前缀 ib./trade.)
# 5) 子项失败则记录 errors[], partial=True
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_status_overview.py::test_ib_status_overview_shape -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/services/ib_status_overview.py backend/tests/test_ib_status_overview.py
git commit -m "feat: add ib status overview schema and service"
```

---

### Task 2: 路由与错误处理（partial/errors）

**Files:**
- Modify: `backend/app/routes/ib.py`
- Modify: `backend/tests/test_ib_status_overview.py`

**Step 1: Write the failing test**

Add test for partial errors:

```python
import types
from app.services import ib_status_overview

def test_ib_status_overview_partial(monkeypatch):
    def broken_stream():
        raise RuntimeError("boom")
    monkeypatch.setattr(ib_status_overview, "_read_stream_status", broken_stream)
    resp = client.get("/api/ib/status/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["partial"] is True
    assert any("stream" in item for item in data["errors"])
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_status_overview.py::test_ib_status_overview_partial -q`
Expected: FAIL

**Step 3: Write minimal implementation**

- 在 `ib_status_overview.py` 把子项读取拆成 `_read_stream_status()` 等小函数，异常时捕获并写入 `errors[]`，设置 `partial=True`。
- 在 `backend/app/routes/ib.py` 新增路由：

```python
@router.get("/status/overview", response_model=IBStatusOverviewOut)
def get_ib_status_overview():
    with get_session() as session:
        payload = build_ib_status_overview(session)
        return IBStatusOverviewOut(**payload)
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_status_overview.py::test_ib_status_overview_partial -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/routes/ib.py backend/app/services/ib_status_overview.py backend/tests/test_ib_status_overview.py
git commit -m "feat: expose ib status overview endpoint"
```

---

### Task 3: 前端面板与轮询

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Write the failing test**

如果没有现成前端测试框架覆盖页面，先增加一个最小化的渲染测试（若项目已有 Vitest + React Testing Library 配置）：

```tsx
import { render, screen } from "@testing-library/react";
import LiveTradePage from "../pages/LiveTradePage";

test("renders overview panel title", () => {
  render(<LiveTradePage />);
  expect(screen.getByText("连接状态面板")).toBeInTheDocument();
});
```

**Step 2: Run test to verify it fails**

Run: `npm test -- LiveTradePage` 或对应 Vitest 命令
Expected: FAIL

**Step 3: Write minimal implementation**

- 新增接口类型 `IBStatusOverview`，新增 `ibOverview` state。
- 新增 `fetchIbOverview()` 调用 `/api/ib/status/overview`，页面加载与定时轮询（5s）。
- 状态卡片显示 `connection/config/stream/snapshot_cache/orders/alerts`，遇 `partial` 显示提示。
- 保持现有表单功能不变（合约、健康检查、历史补齐等）。
- i18n 新增文案：
  - `trade.overviewTitle` / `trade.overviewMeta`
  - `trade.overviewPartial`
  - `trade.overviewRefresh`

**Step 4: Run test to verify it passes**

Run: `npm test -- LiveTradePage`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx
git commit -m "feat: add live trade overview panel"
```

---

### Task 4: 验证与待办更新

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Run backend tests**

Run: `pytest backend/tests/test_ib_status_overview.py -q`
Expected: PASS

**Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build success

**Step 3: Restart frontend service**

Run: `systemctl --user restart stocklean-frontend`

**Step 4: Update TODO status**

将 Phase 0.1/0.2 相关条目勾选完成（或标注完成日期），保持与实现一致。

**Step 5: Commit**

```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "chore: update ib auto trade todo status"
```

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-01-23-ib-live-trade-status-implementation-plan.md`.

Two execution options:

1. Subagent-Driven (this session) — use superpowers:subagent-driven-development
2. Parallel Session (separate) — open new session with superpowers:executing-plans

Which approach?
