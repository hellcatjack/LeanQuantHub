# IB 行情订阅实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 IB 行情订阅（Streaming）服务与 API，并提供最小 UI 入口用于启动/停止订阅与查看状态。

**Architecture:** 新增 `IBStreamRunner` 常驻订阅器，按“决策快照优先/项目主题回退”的规则生成订阅集合；IB L1 tick 持续写入 `data/ib/stream/{symbol}.json`，状态写入 `_status.json`。断线时进入 `degraded` 并用 snapshot/history 回退写入。

**Tech Stack:** FastAPI, SQLAlchemy, ibapi, React (LiveTradePage)

---

### Task 1: 订阅集合选择规则（决策快照优先）

**Files:**
- Create: `backend/app/services/ib_stream.py`
- Modify: `backend/app/services/decision_snapshot.py` (仅在需要时复用已有读取逻辑)
- Test: `backend/tests/test_ib_stream_symbols.py`

**Step 1: Write the failing test**

```python
def test_stream_symbols_prefers_snapshot(session, sample_snapshot):
    symbols = build_stream_symbols(session, project_id=1, decision_snapshot_id=sample_snapshot.id)
    assert symbols == ["AAPL", "NVDA"]
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_symbols.py::test_stream_symbols_prefers_snapshot -q`
Expected: FAIL (build_stream_symbols not implemented)

**Step 3: Write minimal implementation**

```python
def build_stream_symbols(session, project_id: int, decision_snapshot_id: int | None):
    if decision_snapshot_id:
        # read snapshot items.csv
        return symbols
    # fallback to project symbols
    return fallback_symbols
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_symbols.py::test_stream_symbols_prefers_snapshot -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_symbols.py
git commit -m "feat: add ib stream symbol selection"
```

---

### Task 2: Streaming 状态文件与降级标记

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_status.py`

**Step 1: Write the failing test**

```python
def test_stream_status_written(tmp_path):
    status = write_stream_status(tmp_path, status="connected", symbols=["SPY"])
    assert status["status"] == "connected"
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_status.py::test_stream_status_written -q`
Expected: FAIL (write_stream_status missing)

**Step 3: Write minimal implementation**

```python
def write_stream_status(root, status, symbols, error=None, market_data_type="delayed"):
    # write _status.json
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_status.py::test_stream_status_written -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_status.py
git commit -m "feat: add ib stream status writer"
```

---

### Task 3: IB Streaming Runner（Mock/Live）

**Files:**
- Modify: `backend/app/services/ib_market.py` (如需共享 contract/adapter 工具)
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: Write the failing test**

```python
def test_stream_runner_mock_writes_files(tmp_path, monkeypatch, session):
    runner = IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")
    runner._write_tick("SPY", {"last": 480.0})
    assert (tmp_path / "stream" / "SPY.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_mock_writes_files -q`
Expected: FAIL (IBStreamRunner missing)

**Step 3: Write minimal implementation**

```python
class IBStreamRunner:
    def __init__(...): ...
    def _write_tick(...): ...
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_mock_writes_files -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: add ib stream runner mock path"
```

---

### Task 4: API 接口（start/stop/status）

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/ib.py`
- Test: `backend/tests/test_ib_stream_routes.py`

**Step 1: Write the failing test**

```python
def test_stream_status_route(client):
    res = client.get("/api/ib/stream/status")
    assert res.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_routes.py::test_stream_status_route -q`
Expected: FAIL (route missing)

**Step 3: Write minimal implementation**

```python
@router.get("/stream/status")
def get_ib_stream_status(): ...
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_routes.py::test_stream_status_route -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/routes/ib.py backend/app/schemas.py backend/tests/test_ib_stream_routes.py
git commit -m "feat: add ib stream api endpoints"
```

---

### Task 5: LiveTrade 页面订阅卡片

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend` manual check (Playwright)

**Step 1: Write the failing test (Playwright)**

Create a minimal Playwright check (or manual if no suite): start/stop button visible.

**Step 2: Verify it fails**

Expected: UI no stream card.

**Step 3: Implement UI**

Add card showing status, last heartbeat, subscribed count, Start/Stop actions.

**Step 4: Verify it passes (Playwright/manual)**

Run: `npm run build` (in `frontend/`), restart `stocklean-frontend`.

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx
git commit -m "feat: add ib stream status card"
```

---

### Task 6: 回退与互斥（JobLock + degraded）

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_lock.py`

**Step 1: Write the failing test**

```python
def test_stream_lock_busy(monkeypatch):
    with pytest.raises(RuntimeError):
        acquire_stream_lock()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_lock.py::test_stream_lock_busy -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def acquire_stream_lock():
    JobLock("ib_stream", data_root)
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_lock.py::test_stream_lock_busy -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_lock.py
git commit -m "feat: add ib stream lock and degraded handling"
```

---

### Task 7: 回归测试

**Step 1: Run backend tests**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests -q`

**Step 2: Run frontend build**

Run: `cd frontend && npm run build`

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: verify ib stream implementation"
```

