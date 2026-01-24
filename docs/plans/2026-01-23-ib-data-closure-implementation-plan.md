# IB 数据闭环 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现“按需订阅 IB 行情 → 快照落盘 → 交易/风控读取 → 前端展示”的最小闭环。

**Architecture:** 后端新增订阅任务 Runner，写入 `data/ib/stream` 快照与状态文件；交易/风控读取本地快照回退；前端 LiveTrade 新增 Yahoo 风格行情卡片与状态展示。

**Tech Stack:** FastAPI, SQLAlchemy, IB API(ibapi), React + Vite, Playwright(可选)

### Task 1: 新增订阅任务 Runner（后端）

**Files:**
- Create: `backend/app/services/ib_stream_runner.py`
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_ib_stream_runner.py
from pathlib import Path
from app.services.ib_stream_runner import StreamSnapshotWriter


def test_stream_snapshot_writer_writes_symbol_snapshot(tmp_path: Path):
    writer = StreamSnapshotWriter(tmp_path)
    writer.write_snapshot("SPY", {"last": 100.0, "timestamp": "2026-01-23T00:00:00Z"})
    assert (tmp_path / "SPY.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_snapshot_writer_writes_symbol_snapshot -v`
Expected: FAIL with "ModuleNotFoundError" or missing class

**Step 3: Write minimal implementation**

```python
# backend/app/services/ib_stream_runner.py
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

class StreamSnapshotWriter:
    def __init__(self, stream_root: Path) -> None:
        self.stream_root = stream_root
        self.stream_root.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, symbol: str, payload: dict) -> None:
        path = self.stream_root / f"{symbol}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_snapshot_writer_writes_symbol_snapshot -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream_runner.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: add ib stream snapshot writer"
```

### Task 2: 订阅任务心跳与状态文件落地

**Files:**
- Modify: `backend/app/services/ib_stream_runner.py`
- Modify: `backend/app/services/ib_stream.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_ib_stream_runner.py
from pathlib import Path
from app.services.ib_stream_runner import StreamStatusWriter


def test_stream_status_writer_writes_status(tmp_path: Path):
    writer = StreamStatusWriter(tmp_path)
    writer.write_status(status="running", symbols=["SPY"], error=None, market_data_type="delayed")
    assert (tmp_path / "_status.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_status_writer_writes_status -v`
Expected: FAIL with missing class

**Step 3: Write minimal implementation**

```python
# backend/app/services/ib_stream_runner.py
class StreamStatusWriter:
    def __init__(self, stream_root: Path) -> None:
        self.stream_root = stream_root
        self.stream_root.mkdir(parents=True, exist_ok=True)

    def write_status(self, *, status: str, symbols: list[str], error: str | None, market_data_type: str) -> None:
        payload = {
            "status": status,
            "last_heartbeat": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "subscribed_symbols": sorted({s.upper() for s in symbols}),
            "ib_error_count": 0 if not error else 1,
            "last_error": error,
            "market_data_type": market_data_type,
        }
        (self.stream_root / "_status.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_status_writer_writes_status -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream_runner.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: add ib stream status writer"
```

### Task 3: 订阅任务执行骨架（按需启动）

**Files:**
- Modify: `backend/app/services/ib_stream_runner.py`
- Modify: `backend/app/routes/ib.py`
- Test: `backend/tests/test_ib_stream_runner.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_ib_stream_runner.py
from pathlib import Path
from app.services.ib_stream_runner import StreamRunConfig


def test_stream_run_config_defaults(tmp_path: Path):
    cfg = StreamRunConfig(stream_root=tmp_path, symbols=["SPY"], market_data_type="delayed")
    assert cfg.symbols == ["SPY"]
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_run_config_defaults -v`
Expected: FAIL with missing class

**Step 3: Write minimal implementation**

```python
# backend/app/services/ib_stream_runner.py
from dataclasses import dataclass

@dataclass
class StreamRunConfig:
    stream_root: Path
    symbols: list[str]
    market_data_type: str
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ib_stream_runner.py::test_stream_run_config_defaults -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/ib_stream_runner.py backend/tests/test_ib_stream_runner.py
git commit -m "feat: add ib stream run config"
```

### Task 4: 交易/风控读取本地快照回退

**Files:**
- Modify: `backend/app/services/trade_guard.py`
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_guard.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_trade_guard.py
from pathlib import Path
import json
from app.services.trade_guard import _read_local_snapshot


def test_read_local_snapshot(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "ib" / "stream"
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "SPY.json").write_text(json.dumps({"last": 10}), encoding="utf-8")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    assert _read_local_snapshot("SPY") == {"last": 10}
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_guard.py::test_read_local_snapshot -v`
Expected: FAIL if _read_local_snapshot not using DATA_ROOT

**Step 3: Write minimal implementation**

```python
# backend/app/services/trade_guard.py
# ensure _ib_stream_root uses DATA_ROOT when present (already does) and _read_local_snapshot reads local file
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_trade_guard.py::test_read_local_snapshot -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_guard.py backend/tests/test_trade_guard.py
git commit -m "test: validate local snapshot fallback"
```

### Task 5: 前端 LiveTrade 行情卡片（Yahoo 风格）

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Test: `frontend/src/pages/LiveTradePage.test.tsx`

**Step 1: Write the failing test**

```tsx
// frontend/src/pages/LiveTradePage.test.tsx
import { render, screen } from "@testing-library/react";
import LiveTradePage from "./LiveTradePage";

test("renders market snapshot card", () => {
  render(<LiveTradePage />);
  expect(screen.getByText(/行情快照/i)).toBeInTheDocument();
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- --runTestsByPath src/pages/LiveTradePage.test.tsx`
Expected: FAIL (card not found)

**Step 3: Write minimal implementation**

```tsx
// LiveTradePage.tsx
// add card section with title "行情快照" and fields: price, change, change_pct, volume
```

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- --runTestsByPath src/pages/LiveTradePage.test.tsx`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx frontend/src/pages/LiveTradePage.test.tsx
git commit -m "feat: add live trade market snapshot card"
```

### Task 6: 文档与 TODO 更新

**Files:**
- Modify: `docs/todolists/IBAutoTradeTODO.md`

**Step 1: Update TODO statuses**
- 标记 Phase 1.2 “实时行情订阅” 为完成（若全部实现并验收通过）。

**Step 2: Commit**

```bash
git add docs/todolists/IBAutoTradeTODO.md
git commit -m "docs: update IB auto trade todo for data closure"
```

---

**Execution Handoff**
Plan complete and saved to `docs/plans/2026-01-23-ib-data-closure-implementation-plan.md`. Two execution options:

1. Subagent-Driven (this session) – I dispatch fresh subagent per task, review between tasks.
2. Parallel Session (separate) – Open new session with executing-plans, batch execution with checkpoints.

Which approach?
