# IB PreTrade 行情快照（Phase 0–1）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan.

**Goal:** 在 PreTrade 流程中加入“短时行情快照”步骤，支持项目级 `market_data_type` 与 TTL，保证实盘/模拟盘在执行前使用 IB 行情快照。

**Architecture:** PreTrade 新增 `market_snapshot` 步骤，读取项目配置（`trade.market_data_type`、`trade.market_snapshot_ttl_seconds`），使用 IB 快照写入 `data/ib/stream`，并通过 TTL 进行幂等。连接状态与 stream 状态统一在步骤内更新。

**Tech Stack:** FastAPI + SQLAlchemy + Pytest

---

### Task 1: 连接状态新增 degraded_since

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/ib_settings.py`
- Create: `deploy/mysql/patches/20260123_ib_connection_state_degraded_since.sql`
- Test: `backend/tests/test_ib_connection_state_degraded_since.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services.ib_settings import update_ib_state


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_ib_state_degraded_since_clears_on_recovery():
    session = _make_session()
    try:
        state = update_ib_state(session, status="degraded", message="ib down", heartbeat=True)
        assert state.degraded_since is not None
        state = update_ib_state(session, status="connected", message="ok", heartbeat=True)
        assert state.degraded_since is None
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_connection_state_degraded_since.py -q`
Expected: FAIL (字段不存在)

**Step 3: Write minimal implementation**

- `backend/app/models.py`：`IBConnectionState` 新增 `degraded_since: datetime | None` 字段。
- `backend/app/schemas.py`：`IBConnectionStateOut` 增加 `degraded_since`。
- `backend/app/services/ib_settings.py`：
  - 当 `status == "degraded"` 且 `degraded_since` 为空时写入当前时间；
  - 当 `status in {"connected", "mock"}` 时清空 `degraded_since`。
- `deploy/mysql/patches/20260123_ib_connection_state_degraded_since.sql`：新增字段 + 变更说明 + 回滚指引 + `schema_migrations` 记录。

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_connection_state_degraded_since.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/models.py backend/app/schemas.py backend/app/services/ib_settings.py deploy/mysql/patches/20260123_ib_connection_state_degraded_since.sql backend/tests/test_ib_connection_state_degraded_since.py
git commit -m "feat: track ib degraded_since"
```

---

### Task 2: 行情快照 TTL 幂等判断

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_snapshot_ttl.py`

**Step 1: Write the failing test**

```python
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_stream


def test_snapshot_ttl_respects_symbols_and_time(tmp_path):
    stream_root = tmp_path / "ib" / "stream"
    stream_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "last_heartbeat": (datetime.utcnow() - timedelta(seconds=5)).isoformat() + "Z",
        "subscribed_symbols": ["SPY", "AAPL"],
        "ib_error_count": 0,
        "last_error": None,
        "market_data_type": "realtime",
    }
    (stream_root / "_status.json").write_text(json.dumps(payload), encoding="utf-8")

    assert ib_stream.is_snapshot_fresh(stream_root, ["SPY", "AAPL"], ttl_seconds=30) is True
    assert ib_stream.is_snapshot_fresh(stream_root, ["SPY"], ttl_seconds=30) is False
    assert ib_stream.is_snapshot_fresh(stream_root, ["SPY", "AAPL"], ttl_seconds=1) is False
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_stream_snapshot_ttl.py -q`
Expected: FAIL（函数不存在）

**Step 3: Write minimal implementation**

在 `backend/app/services/ib_stream.py` 增加：

```python
def is_snapshot_fresh(stream_root: Path, symbols: Iterable[str], ttl_seconds: int | None) -> bool:
    status = get_stream_status(stream_root.parent)
    last_heartbeat = status.get("last_heartbeat")
    if not last_heartbeat:
        return False
    if ttl_seconds is None:
        return False
    # 解析 ISO 时间
    try:
        ts = datetime.fromisoformat(str(last_heartbeat).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return False
    if datetime.utcnow() - ts > timedelta(seconds=int(ttl_seconds)):
        return False
    current = sorted({_normalize_symbol(s) for s in status.get("subscribed_symbols") or [] if _normalize_symbol(s)})
    expected = sorted({_normalize_symbol(s) for s in symbols if _normalize_symbol(s)})
    return current == expected and bool(expected)
```

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_stream_snapshot_ttl.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_snapshot_ttl.py
git commit -m "feat: add ib snapshot ttl helper"
```

---

### Task 3: 支持 market_data_type 覆盖

**Files:**
- Modify: `backend/app/services/ib_market.py`
- Test: `backend/tests/test_ib_market_snapshot_override.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
from types import SimpleNamespace
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_market

class _DummyQuery:
    def filter(self, *args, **kwargs):
        return self
    def one_or_none(self):
        return None

class _DummySession:
    def query(self, *args, **kwargs):
        return _DummyQuery()


def test_fetch_market_snapshots_uses_override(monkeypatch, tmp_path):
    called = {"value": None}

    def _market_data_type_id(value):
        called["value"] = value
        return 3

    monkeypatch.setattr(ib_market, "_market_data_type_id", _market_data_type_id)
    monkeypatch.setattr(ib_market, "ensure_ib_client_id", lambda _session, **_kwargs: SimpleNamespace(
        market_data_type="realtime", use_regulatory_snapshot=False, api_mode="mock"
    ))

    session = _DummySession()
    ib_market.fetch_market_snapshots(session, symbols=["SPY"], store=False, market_data_type="delayed")
    assert called["value"] == "delayed"
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_market_snapshot_override.py -q`
Expected: FAIL（函数签名不支持）

**Step 3: Write minimal implementation**

在 `backend/app/services/ib_market.py` 中：
- 扩展 `fetch_market_snapshots(..., market_data_type: str | None = None)`；
- 当 `market_data_type` 有值时优先 `_market_data_type_id(market_data_type)`，否则使用 `settings_row.market_data_type`；
- 其余逻辑不变。

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_ib_market_snapshot_override.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_market.py backend/tests/test_ib_market_snapshot_override.py
git commit -m "feat: allow market_data_type override for snapshots"
```

---

### Task 4: PreTrade 新增 market_snapshot 步骤

**Files:**
- Modify: `backend/app/services/pretrade_runner.py`
- Modify: `backend/app/routes/projects.py`（读取项目配置）
- Test: `backend/tests/test_pretrade_market_snapshot.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, PreTradeRun, PreTradeStep, Project, DecisionSnapshot
from app.services import pretrade_runner


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_pretrade_market_snapshot_calls_fetch(monkeypatch, tmp_path):
    session = _make_session()
    try:
        project = Project(name="pretrade-snap", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "items.csv"
        items_path.write_text("symbol\nSPY\nAAPL\n", encoding="utf-8")
        snapshot = DecisionSnapshot(project_id=project.id, items_path=str(items_path))
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = PreTradeRun(project_id=project.id, status="running", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(run_id=run.id, step_key="market_snapshot", step_order=9, status="queued",
                            artifacts={"decision_snapshot_id": snapshot.id})
        session.add(step)
        session.commit()
        session.refresh(step)

        called = {"ok": False, "symbols": None, "market_data_type": None}

        def _fetch_market_snapshots(_session, *, symbols, store, market_data_type=None, **_kwargs):
            called["ok"] = True
            called["symbols"] = symbols
            called["market_data_type"] = market_data_type
            return [{"symbol": "SPY", "data": {"last": 1.0}, "error": None}]

        monkeypatch.setattr(pretrade_runner, "fetch_market_snapshots", _fetch_market_snapshots)
        monkeypatch.setattr(pretrade_runner, "_resolve_project_config", lambda _session, _pid: {
            "trade": {"market_data_type": "delayed", "market_snapshot_ttl_seconds": 30}
        })
        monkeypatch.setattr(pretrade_runner.ib_stream, "is_snapshot_fresh", lambda *_args, **_kwargs: False)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_market_snapshot(ctx, {})

        assert called["ok"] is True
        assert called["market_data_type"] == "delayed"
        assert "market_snapshot" in (result.artifacts or {})
    finally:
        session.close()
```

**Step 2: Run test to verify it fails**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_pretrade_market_snapshot.py -q`
Expected: FAIL（步骤不存在）

**Step 3: Write minimal implementation**

在 `backend/app/services/pretrade_runner.py`：
- 新增 `step_market_snapshot`：
  - 读取项目配置 `trade.market_data_type`、`trade.market_snapshot_ttl_seconds`；
  - 使用 `ib_stream.build_stream_symbols(session, project_id, decision_snapshot_id, max_symbols)`；
  - 若 `ib_stream.is_snapshot_fresh(stream_root, symbols, ttl_seconds)` 为 True，则返回 `skipped=true`；
  - 否则调用 `fetch_market_snapshots(..., store=True, market_data_type=...)`；
  - 根据结果更新 `ib_stream.write_stream_status` 和 `update_ib_state`；
  - artifacts 中记录 `skipped` 与 `symbols`。
- 将 `("market_snapshot", step_market_snapshot)` 插入 `STEP_DEFS`，位置在 `decision_snapshot` 之后、`trade_execute` 之前。

**Step 4: Run test to verify it passes**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_pretrade_market_snapshot.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/pretrade_runner.py backend/tests/test_pretrade_market_snapshot.py
git commit -m "feat: add pretrade market snapshot step"
```

---

### Task 5: 回归测试

**Step 1: Run full backend tests**

Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests -q`
Expected: PASS

**Step 2: Commit (if any fixes)**

```bash
git add -A
git commit -m "test: stabilize pretrade snapshot"
```

---

Plan complete and saved to `docs/plans/2026-01-23-ib-pretrade-market-plan.md`. Two execution options:

1. Subagent-Driven (this session) - I dispatch fresh subagent per task, review between tasks
2. Parallel Session (separate) - Open new session with executing-plans, batch execution with checkpoints

Which approach?
