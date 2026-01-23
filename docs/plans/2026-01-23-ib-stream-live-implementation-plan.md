# IB 实时行情订阅（Live）实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 接入真实 ibapi L1 行情订阅，落盘 `data/ib/stream/{SYMBOL}.json`，状态 `_status.json` 可监控，并提供轻量回退与真实联通验证。

**Architecture:** `IBStreamRunner` 作为常驻进程，读取 `_config.json` 决定订阅集合（决策快照优先），通过 ibapi 回调写盘并维护状态；若 tick 过期或错误累计，触发 snapshot 补写并进入 `degraded`。

**Tech Stack:** FastAPI, SQLAlchemy, ibapi, pytest

---

## Task 1: 扩展 Stream Status 字段与 Schema

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_ib_stream_status.py`

**Step 1: 写失败测试（新增字段）**
```python
# backend/tests/test_ib_stream_status.py
from app.services import ib_stream

def test_stream_status_exposes_degraded_fields(tmp_path):
    status = ib_stream.write_stream_status(
        tmp_path,
        status="degraded",
        symbols=["SPY"],
        market_data_type="delayed",
        degraded_since="2026-01-23T00:00:00Z",
        last_snapshot_refresh="2026-01-23T00:00:10Z",
        source="ib_snapshot",
    )
    assert status["degraded_since"] == "2026-01-23T00:00:00Z"
    loaded = ib_stream.get_stream_status(tmp_path)
    assert loaded["degraded_since"] == "2026-01-23T00:00:00Z"
    assert loaded["last_snapshot_refresh"] == "2026-01-23T00:00:10Z"
    assert loaded["source"] == "ib_snapshot"
```

**Step 2: 运行测试（应失败）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_status.py::test_stream_status_exposes_degraded_fields -q`
Expected: FAIL（字段未实现）

**Step 3: 实现最小代码**
```python
# backend/app/services/ib_stream.py

def write_stream_status(..., degraded_since: str | None = None, last_snapshot_refresh: str | None = None, source: str | None = None):
    payload = {
        ...,
        "degraded_since": degraded_since,
        "last_snapshot_refresh": last_snapshot_refresh,
        "source": source,
    }


def get_stream_status(...):
    return {
        ...,
        "degraded_since": payload.get("degraded_since"),
        "last_snapshot_refresh": payload.get("last_snapshot_refresh"),
        "source": payload.get("source"),
    }
```

```python
# backend/app/schemas.py
class IBStreamStatusOut(BaseModel):
    ...
    degraded_since: str | None = None
    last_snapshot_refresh: str | None = None
    source: str | None = None
```

**Step 4: 运行测试（应通过）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_status.py::test_stream_status_exposes_degraded_fields -q`
Expected: PASS

**Step 5: 提交**
```bash
git add backend/app/services/ib_stream.py backend/app/schemas.py backend/tests/test_ib_stream_status.py
git commit -m "feat: add ib stream degraded status fields"
```

---

## Task 2: Stream Runner 支持 stale 回退与 tick 记录

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: 写失败测试（stale 回退）**
```python
# backend/tests/test_ib_stream_runner.py
from datetime import datetime, timedelta
import json
import app.services.ib_stream as ib_stream


def test_stream_runner_refreshes_snapshot_when_stale(tmp_path, monkeypatch):
    runner = ib_stream.IBStreamRunner(
        project_id=1,
        decision_snapshot_id=3,
        refresh_interval_seconds=5,
        stale_seconds=1,
        data_root=tmp_path,
        api_mode="mock",
    )
    runner._last_tick_ts["SPY"] = datetime.utcnow() - timedelta(seconds=10)

    def _fake_snapshots(*args, **kwargs):
        return [{"symbol": "SPY", "data": {"last": 101.0}}]

    monkeypatch.setattr(ib_stream, "fetch_market_snapshots", _fake_snapshots)
    runner._refresh_snapshot_if_stale(["SPY"])

    payload = json.loads((tmp_path / "stream" / "SPY.json").read_text(encoding="utf-8"))
    assert payload["source"] == "ib_snapshot"
```

**Step 2: 运行测试（应失败）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_refreshes_snapshot_when_stale -q`
Expected: FAIL（方法不存在）

**Step 3: 实现最小代码**
```python
# backend/app/services/ib_stream.py
from datetime import datetime, timedelta
from app.services.ib_market import fetch_market_snapshots

class IBStreamRunner:
    def __init__(..., stale_seconds: int = 15, ...):
        ...
        self.stale_seconds = stale_seconds
        self._last_tick_ts: dict[str, datetime] = {}
        self._degraded_since: str | None = None
        self._last_snapshot_refresh: str | None = None

    def _handle_tick(self, symbol: str, tick: dict[str, Any], source: str = "ib_stream") -> None:
        self._last_tick_ts[_normalize_symbol(symbol)] = datetime.utcnow()
        self._write_tick(symbol, tick, source=source)

    def _refresh_snapshot_if_stale(self, symbols: list[str]) -> None:
        now = datetime.utcnow()
        stale = []
        for symbol in symbols:
            last = self._last_tick_ts.get(_normalize_symbol(symbol))
            if last is None or (now - last) > timedelta(seconds=self.stale_seconds):
                stale.append(symbol)
        if not stale:
            return
        snapshots = fetch_market_snapshots(symbols=stale)
        for item in snapshots:
            self._handle_tick(item.get("symbol"), item.get("data") or {}, source="ib_snapshot")
        if self._degraded_since is None:
            self._degraded_since = _utc_now()
        self._last_snapshot_refresh = _utc_now()
```

**Step 4: 运行测试（应通过）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_refreshes_snapshot_when_stale -q`
Expected: PASS

**Step 5: 提交**
```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: add ib stream stale snapshot refresh"
```

---

## Task 3: ibapi Streaming Client（真实订阅）

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: 写失败测试（tick 记录）**
```python
# backend/tests/test_ib_stream_runner.py
from datetime import datetime
import app.services.ib_stream as ib_stream


def test_stream_runner_records_tick_timestamp(tmp_path):
    runner = ib_stream.IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")
    assert "SPY" not in runner._last_tick_ts
    runner._handle_tick("SPY", {"last": 123.0}, source="ib_stream")
    assert "SPY" in runner._last_tick_ts
```

**Step 2: 运行测试（应失败）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_records_tick_timestamp -q`
Expected: FAIL（_handle_tick 未实现）

**Step 3: 实现 ibapi client + 接入 runner**
```python
# backend/app/services/ib_stream.py
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract

_PRICE_TICKS = {1: "bid", 2: "ask", 4: "last", 6: "high", 7: "low", 9: "close"}
_SIZE_TICKS = {0: "bid_size", 3: "ask_size", 5: "last_size", 8: "volume"}

class IBStreamClient(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, on_tick):
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._thread = None
        self._req_id = 1
        self._req_map: dict[int, str] = {}
        self._on_tick = on_tick
        self._error: str | None = None

    def start(self):
        self.connect(self._host, self._port, self._client_id)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.isConnected():
            self.disconnect()

    def subscribe(self, symbols: list[str]):
        for symbol in symbols:
            req_id = self._req_id
            self._req_id += 1
            contract = Contract()
            contract.symbol = symbol
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            self._req_map[req_id] = symbol
            self.reqMktData(req_id, contract, "", False, False, [])

    def tickPrice(self, reqId, tickType, price, attrib):
        key = _PRICE_TICKS.get(tickType)
        if key and reqId in self._req_map:
            self._on_tick(self._req_map[reqId], {key: price})

    def tickSize(self, reqId, tickType, size):
        key = _SIZE_TICKS.get(tickType)
        if key and reqId in self._req_map:
            self._on_tick(self._req_map[reqId], {key: size})
```

**Step 4: 运行测试（应通过）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_records_tick_timestamp -q`
Expected: PASS

**Step 5: 提交**
```bash
git add backend/app/services/ib_stream.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: add ibapi stream client"
```

---

## Task 4: 连接循环与脚本执行

**Files:**
- Modify: `backend/app/services/ib_stream.py`
- Modify: `scripts/run_ib_stream.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: 写失败测试（mock loop 更新 status）**
```python
# backend/tests/test_ib_stream_runner.py
import app.services.ib_stream as ib_stream


def test_stream_runner_loop_writes_status(tmp_path):
    runner = ib_stream.IBStreamRunner(project_id=1, data_root=tmp_path, api_mode="mock")
    runner._write_status_update(["SPY"], market_data_type="delayed")
    status = ib_stream.get_stream_status(tmp_path)
    assert status["status"] in {"connected", "degraded"}
```

**Step 2: 运行测试（应失败）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_loop_writes_status -q`
Expected: FAIL

**Step 3: 实现最小代码**
```python
# backend/app/services/ib_stream.py
class IBStreamRunner:
    ...
    def _write_status_update(self, symbols: list[str], market_data_type: str, status: str = "connected", error: str | None = None):
        return write_stream_status(
            self._stream_root,
            status=status,
            symbols=symbols,
            market_data_type=market_data_type,
            error=error,
            degraded_since=self._degraded_since,
            last_snapshot_refresh=self._last_snapshot_refresh,
            source="ib_stream",
        )

    def run_forever(self):
        settings = get_or_create_ib_settings(SessionLocal())
        ...  # 读取 config，订阅 symbols，循环 refresh_interval_seconds
```

```python
# scripts/run_ib_stream.py
config = ib_stream.read_stream_config(stream_root)
runner = ib_stream.IBStreamRunner(
    project_id=config.get("project_id"),
    decision_snapshot_id=config.get("decision_snapshot_id"),
    refresh_interval_seconds=config.get("refresh_interval_seconds") or 5,
    stale_seconds=config.get("stale_seconds") or 15,
    data_root=stream_root.parent,
    api_mode=ib_settings.api_mode,
)
runner.run_forever()
```

**Step 4: 运行测试（应通过）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_runner.py::test_stream_runner_loop_writes_status -q`
Expected: PASS

**Step 5: 提交**
```bash
git add backend/app/services/ib_stream.py scripts/run_ib_stream.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: run ib stream loop"
```

---

## Task 5: API start/stop 写入 refresh/stale 参数

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/ib.py`
- Test: `backend/tests/test_ib_stream_routes.py`

**Step 1: 写失败测试（config 写入新字段）**
```python
# backend/tests/test_ib_stream_routes.py
from app.services import ib_stream

def test_start_stream_writes_refresh_params(tmp_path):
    ib_stream.write_stream_config(tmp_path, {"refresh_interval_seconds": 5, "stale_seconds": 15})
    payload = ib_stream.read_stream_config(tmp_path)
    assert payload["refresh_interval_seconds"] == 5
    assert payload["stale_seconds"] == 15
```

**Step 2: 运行测试（应失败）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_routes.py::test_start_stream_writes_refresh_params -q`
Expected: FAIL

**Step 3: 实现最小改动**
```python
# backend/app/schemas.py
class IBStreamStartRequest(BaseModel):
    ...
    refresh_interval_seconds: int | None = None
    stale_seconds: int | None = None
```

```python
# backend/app/routes/ib.py
ib_stream.write_stream_config(
    stream_root,
    {
        ...,
        "refresh_interval_seconds": payload.refresh_interval_seconds,
        "stale_seconds": payload.stale_seconds,
    },
)
```

**Step 4: 运行测试（应通过）**
Run: `/app/stocklean/.venv/bin/pytest backend/tests/test_ib_stream_routes.py::test_start_stream_writes_refresh_params -q`
Expected: PASS

**Step 5: 提交**
```bash
git add backend/app/schemas.py backend/app/routes/ib.py backend/tests/test_ib_stream_routes.py
git commit -m "feat: persist ib stream refresh params"
```

---

## Task 6: 回归与真实联通验证

**Step 1: 后端测试**
Run: `/app/stocklean/.venv/bin/pytest backend/tests -q`
Expected: PASS

**Step 2: 真实联通验证（手动）**
1. 设置 IB 配置（已就绪）：`/api/ib/settings`
2. 启动订阅（快照 ID=3，max 50，refresh 5s）
3. 观察 `data/ib/stream/_status.json` 状态变化。
4. 校验至少 3 个标的 JSON 持续刷新。
5. 断开 Gateway，观察 `disconnected`，恢复后回到 `connected`。

**Step 3: 提交验证记录**
```bash
git add -A
git commit -m "chore: verify ib stream live"
```

---

## 执行指引
- Phase 1：Task 1-3（状态字段 + stale 回退 + ibapi client）
- Phase 2：Task 4-5（run loop + API config）
- Phase 3：Task 6（回归与联通验证）
