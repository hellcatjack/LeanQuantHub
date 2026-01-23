# IB ClientId Auto-Increment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 当 IB 连接因 clientId 冲突失败时，系统自动递增 client_id 并持久化；默认值为 101。

**Architecture:** 在 `ib_settings` 中新增 clientId 冲突识别与自增探测函数；`probe_ib_connection` 和所有实际 IB 连接调用点统一通过该函数获取可用 client_id。`ib_market`/`ib_history_runner`/`trade_executor` 等使用更新后的 settings。

**Tech Stack:** FastAPI + SQLAlchemy + ibapi（可选依赖）+ pytest

---

### Task 1: 添加 clientId 冲突识别与自增探测（TDD）

**Files:**
- Create: `backend/tests/test_ib_settings_client_id.py`
- Modify: `backend/app/services/ib_settings.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, IBSettings
from app.services import ib_settings


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_ensure_ib_client_id_auto_increments(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        calls = {"n": 0}
        def _fake_probe(host, port, client_id, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return ("disconnected", "ibapi error 326 clientId in use")
            return ("connected", "ibapi ok")

        monkeypatch.setattr(ib_settings, "_probe_ib_api", _fake_probe)

        updated = ib_settings.ensure_ib_client_id(session, max_attempts=3, timeout_seconds=0.1)
        assert updated.client_id == 102
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_settings_client_id.py::test_ensure_ib_client_id_auto_increments -q`
Expected: FAIL（`ensure_ib_client_id` 不存在）

**Step 3: Write minimal implementation**

在 `backend/app/services/ib_settings.py` 新增：

```python
_CLIENT_ID_CONFLICT_MARKERS = ("clientid", "client id", "client_id")


def _is_client_id_conflict(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    if any(marker in lowered for marker in _CLIENT_ID_CONFLICT_MARKERS):
        return "in use" in lowered or "duplicate" in lowered or "already" in lowered
    return False


def ensure_ib_client_id(session, *, max_attempts: int = 5, timeout_seconds: float = 2.0) -> IBSettings:
    settings = get_or_create_ib_settings(session)
    if resolve_ib_api_mode(settings) == "mock":
        return settings
    host = settings.host
    port = settings.port
    client_id = int(settings.client_id or 101)
    attempts = max(1, int(max_attempts))
    for _ in range(attempts):
        result = _probe_ib_api(host, port, client_id, timeout_seconds)
        if result:
            status, message = result
            if status == "connected":
                if client_id != settings.client_id:
                    settings.client_id = client_id
                    session.commit()
                    session.refresh(settings)
                return settings
            if _is_client_id_conflict(message):
                client_id += 1
                continue
        break
    return settings
```

并在 `ProbeClient.error` 中把 clientId 冲突视为连接错误：

```python
if _is_client_id_conflict(errorString):
    self._error = f"client_id_conflict {errorCode} {errorString}"
    self._ready.set()
    return
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_settings_client_id.py::test_ensure_ib_client_id_auto_increments -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_ib_settings_client_id.py backend/app/services/ib_settings.py
git commit -m "feat: auto-increment ib client id on conflict"
```

---

### Task 2: 将探测逻辑接入 probe_ib_connection（TDD）

**Files:**
- Modify: `backend/tests/test_ib_settings_client_id.py`
- Modify: `backend/app/services/ib_settings.py`

**Step 1: Write the failing test**

```python
def test_probe_updates_client_id_on_conflict(monkeypatch):
    session = _make_session()
    try:
        row = IBSettings(client_id=101, host="127.0.0.1", port=7497, api_mode="ib")
        session.add(row)
        session.commit()

        calls = {"n": 0}
        def _fake_probe(host, port, client_id, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return ("disconnected", "ibapi error 326 clientId in use")
            return ("connected", "ibapi ok")

        monkeypatch.setattr(ib_settings, "_probe_ib_api", _fake_probe)

        state = ib_settings.probe_ib_connection(session, timeout_seconds=0.1)
        assert state.status in {"connected", "mock"}
        session.refresh(row)
        assert row.client_id == 102
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_settings_client_id.py::test_probe_updates_client_id_on_conflict -q`
Expected: FAIL（未更新 client_id）

**Step 3: Write minimal implementation**

在 `probe_ib_connection` 内先调用 `ensure_ib_client_id`，并使用其返回的 settings 继续探测：

```python
settings = ensure_ib_client_id(session, timeout_seconds=timeout_seconds)
```

并复用 `settings.host/settings.port/settings.client_id`。

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_settings_client_id.py::test_probe_updates_client_id_on_conflict -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_ib_settings_client_id.py backend/app/services/ib_settings.py
git commit -m "feat: probe ib connection auto-resolves client id"
```

---

### Task 3: 默认 client_id 改为 101（TDD）

**Files:**
- Modify: `backend/tests/test_ib_settings_client_id.py`
- Modify: `backend/app/services/ib_settings.py`

**Step 1: Write the failing test**

```python
def test_default_client_id_is_101(monkeypatch):
    monkeypatch.delenv("IB_CLIENT_ID", raising=False)
    defaults = ib_settings._resolve_default_settings()
    assert defaults["client_id"] == 101
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_settings_client_id.py::test_default_client_id_is_101 -q`
Expected: FAIL（当前默认是 1）

**Step 3: Write minimal implementation**

将 `_resolve_default_settings` 里的默认值从 `"1"` 改为 `"101"`。

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_settings_client_id.py::test_default_client_id_is_101 -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_ib_settings_client_id.py backend/app/services/ib_settings.py
git commit -m "feat: default ib client id to 101"
```

---

### Task 4: 接入 ensure_ib_client_id 于所有 IB 连接调用点（TDD）

**Files:**
- Modify: `backend/app/services/ib_market.py`
- Modify: `backend/app/services/ib_history_runner.py`
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/tests/test_ib_market_mock.py`

**Step 1: Write the failing test**

在 `test_ib_market_mock.py` 增加一次断言确保 `ensure_ib_client_id` 被调用：

```python
def test_market_snapshot_uses_ensure_client_id(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    called = {"ok": False}
    def _ensure(session, **kwargs):
        called["ok"] = True
        return SimpleNamespace(market_data_type="realtime", use_regulatory_snapshot=False, api_mode="mock")

    monkeypatch.setattr(ib_market, "ensure_ib_client_id", _ensure)
    session = _DummySession()
    ib_market.fetch_market_snapshots(session, symbols=["SPY"], store=False)
    assert called["ok"] is True
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_market_mock.py::test_market_snapshot_uses_ensure_client_id -q`
Expected: FAIL（未调用 ensure）

**Step 3: Write minimal implementation**

- 在 `ib_market.fetch_market_snapshots / fetch_historical_bars / refresh_contract_cache` 中将
  `get_or_create_ib_settings` 替换为 `ensure_ib_client_id`。
- 在 `ib_history_runner.run_ib_history_job` 中将 `get_or_create_ib_settings` 替换为 `ensure_ib_client_id`。
- 在 `trade_executor._submit_ib_orders` 中将 `get_or_create_ib_settings` 替换为 `ensure_ib_client_id`。

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_market_mock.py::test_market_snapshot_uses_ensure_client_id -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_market.py backend/app/services/ib_history_runner.py backend/app/services/trade_executor.py backend/tests/test_ib_market_mock.py
git commit -m "feat: ensure ib client id before connections"
```

---

### Task 5: 全量测试与结果确认

**Files:**
- (none)

**Step 1: Run test suite**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests -q`
Expected: PASS（允许 Pydantic 警告）

**Step 2: Commit (if needed)**

```bash
git status -sb
```
Expected: clean
