# IB Market Stream Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement IB market streaming subscription, API endpoints, and a minimal LiveTrade UI card for start/stop and status.

**Architecture:** Add `IBStreamRunner` to maintain L1 subscriptions, write `data/ib/stream/{symbol}.json` and `_status.json`, and degrade to snapshot/history on disconnect. Subscription set prefers decision snapshot, with project symbols as fallback.

**Tech Stack:** FastAPI, SQLAlchemy, ibapi, React (LiveTradePage)

---

### Task 1: Subscription set selection (decision snapshot first)

**Files:**
- Create: `backend/app/services/ib_stream.py`
- Modify: `backend/app/services/decision_snapshot.py` (only if reuse helper)
- Test: `backend/tests/test_ib_stream_symbols.py`

**Step 1: Write the failing test**

```python
def test_stream_symbols_prefers_snapshot(session, sample_snapshot):
    symbols = build_stream_symbols(session, project_id=1, decision_snapshot_id=sample_snapshot.id)
    assert symbols == ["AAPL", "NVDA"]
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_symbols.py::test_stream_symbols_prefers_snapshot -q`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def build_stream_symbols(...):
    if decision_snapshot_id:
        return symbols
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

### Task 2: Stream status file + degrade markers

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
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def write_stream_status(...):
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

### Task 3: IB Stream Runner (Mock/Live)

**Files:**
- Modify: `backend/app/services/ib_market.py` (reuse helpers if needed)
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
Expected: FAIL

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

### Task 4: API endpoints (start/stop/status)

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
Expected: FAIL

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

### Task 5: LiveTrade stream card

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: Playwright/manual check

**Step 1: Failing UI check**

Confirm no stream card exists.

**Step 2: Implement UI**

Add status/heartbeat/subscribed count and Start/Stop actions.

**Step 3: Verify**

Run: `cd frontend && npm run build`, then restart `stocklean-frontend`.

**Step 4: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx
git commit -m "feat: add ib stream status card"
```

---

### Task 6: Lock + degraded fallback

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

### Task 7: Regression checks

**Step 1: Run backend tests**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests -q`

**Step 2: Run frontend build**

Run: `cd frontend && npm run build`

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: verify ib stream implementation"
```

