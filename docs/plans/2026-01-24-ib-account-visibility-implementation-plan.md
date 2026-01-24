# IB 账户信息可视化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在实盘交易页展示 IB 模拟账户的核心账户摘要与持仓信息（核心字段 60s 自动刷新，全量字段手动刷新）。

**Architecture:** 后端新增 IB 账户摘要/持仓采集与缓存；前端新增账户概览与持仓表格。核心字段走缓存与定时刷新，全量字段仅手动刷新。

**Tech Stack:** FastAPI + SQLAlchemy, ibapi, React + Vite, pytest, RTL。

---

### Task 1: 定义账户摘要/持仓输出 Schema

**Files:**
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_ib_account_schema.py`

**Step 1: Write the failing test**
```python
def test_ib_account_summary_schema_accepts_optional_fields():
    from app.schemas import IBAccountSummaryOut
    payload = {
        "refreshed_at": "2026-01-24T00:00:00Z",
        "source": "cache",
        "stale": False,
        "items": {"NetLiquidation": 123.0},
        "full": False,
    }
    obj = IBAccountSummaryOut(**payload)
    assert obj.items["NetLiquidation"] == 123.0
```

**Step 2: Run test to verify it fails**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_schema.py::test_ib_account_summary_schema_accepts_optional_fields`
Expected: FAIL with import or schema missing

**Step 3: Write minimal implementation**
Add schemas:
- `IBAccountSummaryOut` with `items: dict[str, float | str | None]`, `refreshed_at`, `source`, `stale`, `full`.
- `IBAccountPositionOut` with `symbol`, `position`, `avg_cost`, `market_price`, `market_value`, `unrealized_pnl`, `realized_pnl`, `account`, `currency`.
- `IBAccountPositionsOut` with `items`, `refreshed_at`, `stale`.

**Step 4: Run test to verify it passes**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_schema.py::test_ib_account_summary_schema_accepts_optional_fields`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/schemas.py backend/tests/test_ib_account_schema.py
git commit -m "feat: add ib account schemas"
```

---

### Task 2: 实现账户摘要解析与缓存

**Files:**
- Modify: `backend/app/services/ib_account.py`
- Create: `backend/tests/test_ib_account_summary.py`

**Step 1: Write the failing test**
```python
def test_filter_summary_whitelist():
    from app.services.ib_account import _filter_summary, CORE_TAGS
    raw = {"NetLiquidation": "100", "Foo": "bar"}
    core = _filter_summary(raw, full=False)
    assert "NetLiquidation" in core
    assert "Foo" not in core
    full = _filter_summary(raw, full=True)
    assert "Foo" in full
```

**Step 2: Run test to verify it fails**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_summary.py::test_filter_summary_whitelist`
Expected: FAIL with import/missing function

**Step 3: Write minimal implementation**
- 在 `ib_account.py` 中实现：
  - `CORE_TAGS` 白名单集合
  - `_parse_value(value: str) -> float | str | None`（数值转 float，空值 None）
  - `_filter_summary(raw: dict[str, str], full: bool) -> dict[str, object]`
  - `read_cached_summary(cache_path)` / `write_cached_summary(cache_path, payload)`
  - `get_account_summary(session, mode: str, full: bool, force_refresh: bool)`
- `fetch_account_summary(session)` 改为调用 `get_account_summary(..., full=False)`，并保留 `cash_available` 兼容字段（从 AvailableFunds 或 CashBalance 取值）。

**Step 4: Run test to verify it passes**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_summary.py::test_filter_summary_whitelist`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/ib_account.py backend/tests/test_ib_account_summary.py
git commit -m "feat: add ib account summary filtering and cache"
```

---

### Task 3: 实现 IB API 账户摘要/持仓采集

**Files:**
- Modify: `backend/app/services/ib_account.py`
- Create: `backend/tests/test_ib_account_positions.py`

**Step 1: Write the failing test**
```python
def test_positions_merge_snapshot():
    from app.services.ib_account import _merge_position_prices
    positions = [{"symbol": "AAPL", "position": 1.0, "avg_cost": 100.0}]
    snapshots = {"AAPL": {"price": 120.0}}
    merged = _merge_position_prices(positions, snapshots)
    assert merged[0]["market_price"] == 120.0
```

**Step 2: Run test to verify it fails**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_positions.py::test_positions_merge_snapshot`
Expected: FAIL with import/missing function

**Step 3: Write minimal implementation**
- 在 `ib_account.py` 添加 IB API 客户端类（参照 `ib_market.py` 模式）：
  - `reqAccountSummary` + `accountSummary` + `accountSummaryEnd`
  - `reqPositions` + `position` + `positionEnd`
  - 设定 timeout 与错误处理
- 添加 `_merge_position_prices`：用 `fetch_market_snapshots` 补齐 `market_price/market_value/unrealized_pnl`。
- 返回结构统一为 dict 列表，货币字段 default "USD"。

**Step 4: Run test to verify it passes**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_positions.py::test_positions_merge_snapshot`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/services/ib_account.py backend/tests/test_ib_account_positions.py
git commit -m "feat: add ib account positions collection"
```

---

### Task 4: 新增 IB 账户 API 路由

**Files:**
- Modify: `backend/app/routes/ib.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_ib_account_routes.py`

**Step 1: Write the failing test**
```python
def test_get_account_summary_route(client, monkeypatch):
    def fake_summary(*args, **kwargs):
        return {"items": {"NetLiquidation": 100.0}, "refreshed_at": None, "source": "cache", "stale": False, "full": False}
    monkeypatch.setattr("app.services.ib_account.get_account_summary", fake_summary)
    res = client.get("/api/ib/account/summary?mode=paper")
    assert res.status_code == 200
    assert res.json()["items"]["NetLiquidation"] == 100.0
```

**Step 2: Run test to verify it fails**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_routes.py::test_get_account_summary_route`
Expected: FAIL 404 or import error

**Step 3: Write minimal implementation**
- 在 `ib.py` 添加：
  - `GET /api/ib/account/summary`
  - `GET /api/ib/account/positions`
  - `POST /api/ib/account/refresh`（可选，触发 full refresh）
- 返回 `IBAccountSummaryOut` / `IBAccountPositionsOut`。

**Step 4: Run test to verify it passes**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q backend/tests/test_ib_account_routes.py::test_get_account_summary_route`
Expected: PASS

**Step 5: Commit**
```bash
git add backend/app/routes/ib.py backend/app/schemas.py backend/tests/test_ib_account_routes.py
git commit -m "feat: add ib account api endpoints"
```

---

### Task 5: 前端 LiveTradePage 增加账户概览与持仓表

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Modify: `frontend/src/pages/LiveTradePage.test.tsx`

**Step 1: Write the failing test**
```tsx
it("renders account summary section", () => {
  const { container } = render(<LiveTradePage />);
  expect(container.textContent).toContain("trade.accountSummaryTitle");
});
```

**Step 2: Run test to verify it fails**
Run: `cd frontend && npm test -- --runTestsByPath src/pages/LiveTradePage.test.tsx`
Expected: FAIL with missing label

**Step 3: Write minimal implementation**
- 增加 API 请求：`/api/ib/account/summary`（自动 60s）与 `/api/ib/account/summary?full=true`（手动刷新）。
- 增加 `accountSummary`、`accountPositions` state 与加载/错误提示。
- UI 新增“账户概览”卡片与“当前持仓”表格。
- i18n 添加 labels（accountSummaryTitle、accountSummaryRefresh、accountSummaryStale、positionsTitle 等）。

**Step 4: Run test to verify it passes**
Run: `cd frontend && npm test -- --runTestsByPath src/pages/LiveTradePage.test.tsx`
Expected: PASS

**Step 5: Commit**
```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/src/pages/LiveTradePage.test.tsx
git commit -m "feat: show ib account summary and positions"
```

---

### Task 6: 更新 TODO 状态 + 集成验证

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Update TODO status**
- 标记“账户信息展示”相关条目为完成。

**Step 2: Run backend tests**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q`
Expected: PASS

**Step 3: Run frontend tests/build**
Run: `cd frontend && npm test`
Expected: PASS
Run: `cd frontend && npm run build`
Expected: build ok

**Step 4: Commit**
```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: update ib autotrade todo status"
```

---

### Task 7: 合并与发布

**Files:**
- None (git operations)

**Step 1: Rebase or merge main**
Run: `git fetch origin && git rebase origin/main`
Expected: clean rebase

**Step 2: Final verification**
Run: `DATA_ROOT=/tmp/stocklean-test pytest -q`
Expected: PASS

**Step 3: Push branch**
Run: `git push -u origin 2026-01-24-ib-account-visibility`

**Step 4: Integrate**
Use superpowers:finishing-a-development-branch to choose merge strategy.
