# IB Client ID Lease Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为直连下单引入 client id 池 + 租约 + 健康探针，解决并发 client id 冲突，并在异常时自动回收。

**Architecture:** 新增 `ib_client_id_pool` 表与服务层 `ib_client_id_pool.py` 管理租约；直连下单先分配 client id、独立输出目录、异步启动 Lean 获取 PID，再更新租约；健康探针在分配前清理过期租约并可自动 kill 进程。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL, pytest, Lean Launcher (dotnet), JSON config.

---

### Task 1: 为 client id 池与直连下单新增失败测试

**Files:**
- Create: `backend/tests/test_ib_client_id_pool.py`
- Modify: `backend/tests/test_lean_execution_config.py`
- Create: `backend/tests/test_trade_direct_order_client_id_pool.py`

**Step 1: 写 client id 池的失败测试**

```python
# backend/tests/test_ib_client_id_pool.py
from datetime import datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base
from app.services import ib_client_id_pool


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_lease_client_id_allocates_unique(monkeypatch):
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 2)
    monkeypatch.setattr(settings, "ib_client_id_live_offset", 5000)

    session = _make_session()
    lease1 = ib_client_id_pool.lease_client_id(session, order_id=1, mode="paper", output_dir="/tmp/a")
    lease2 = ib_client_id_pool.lease_client_id(session, order_id=2, mode="paper", output_dir="/tmp/b")
    assert lease1.client_id != lease2.client_id


def test_lease_client_id_pool_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 1)

    session = _make_session()
    ib_client_id_pool.lease_client_id(session, order_id=1, mode="paper", output_dir="/tmp/a")
    try:
        ib_client_id_pool.lease_client_id(session, order_id=2, mode="paper", output_dir="/tmp/b")
        assert False, "expected ClientIdPoolExhausted"
    except ib_client_id_pool.ClientIdPoolExhausted:
        assert True


def test_reap_stale_leases_releases(monkeypatch):
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 1)
    monkeypatch.setattr(settings, "ib_client_id_lease_ttl_seconds", 1)
    monkeypatch.setattr(settings, "lean_bridge_heartbeat_timeout_seconds", 1)

    session = _make_session()
    lease = ib_client_id_pool.lease_client_id(session, order_id=1, mode="paper", output_dir="/tmp/a")
    lease.acquired_at = datetime.utcnow() - timedelta(seconds=10)
    session.commit()

    released = ib_client_id_pool.reap_stale_leases(session, mode="paper", now=datetime.utcnow())
    assert released == 1
```

**Step 2: 写 build_execution_config 覆盖参数的失败测试**

```python
# backend/tests/test_lean_execution_config.py (append)

def test_execution_config_overrides_client_id_and_output_dir():
    cfg = lean_execution.build_execution_config(
        intent_path="/tmp/intent.json",
        brokerage="InteractiveBrokersBrokerage",
        project_id=16,
        mode="paper",
        client_id=2222,
        lean_bridge_output_dir="/tmp/bridge",
    )
    assert cfg["ib-client-id"] == 2222
    assert cfg["lean-bridge-output-dir"] == "/tmp/bridge"
```

**Step 3: 写直连下单使用池的失败测试**

```python
# backend/tests/test_trade_direct_order_client_id_pool.py
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models import Base, IBClientIdPool
from app.services import trade_direct_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_submit_direct_order_allocates_client_id(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "data_root", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "ib_client_id_pool_base", 900)
    monkeypatch.setattr(settings, "ib_client_id_pool_size", 1)

    captured = {}

    def _fake_launch(config_path: str):
        captured["config_path"] = config_path
        return 4321

    monkeypatch.setattr(trade_direct_order, "launch_execution_async", _fake_launch)

    session = _make_session()
    payload = {
        "project_id": 1,
        "mode": "paper",
        "client_order_id": "manual-1",
        "symbol": "SPY",
        "side": "BUY",
        "quantity": 1,
        "order_type": "MKT",
    }
    result = trade_direct_order.submit_direct_order(session, payload)
    assert result.order_id > 0

    lease = session.query(IBClientIdPool).first()
    assert lease is not None
    assert lease.client_id == 900
    assert lease.pid == 4321
```

**Step 4: 运行测试确认失败**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_ib_client_id_pool.py::test_lease_client_id_allocates_unique -v`
Expected: FAIL (ImportError: ib_client_id_pool or IBClientIdPool missing)

**Step 5: 提交**

```bash
git add backend/tests/test_ib_client_id_pool.py backend/tests/test_lean_execution_config.py backend/tests/test_trade_direct_order_client_id_pool.py
git commit -m "test: add failing ib client id pool tests"
```

---

### Task 2: 新增模型与服务实现 client id 池

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/app/services/ib_client_id_pool.py`

**Step 1: 实现模型（最小可用）**

```python
# backend/app/models.py (append near IB models)
class IBClientIdPool(Base):
    __tablename__ = "ib_client_id_pool"

    client_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="free")
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Step 2: 实现 client id 池服务**

```python
# backend/app/services/ib_client_id_pool.py
from __future__ import annotations

import os
import signal
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_

from app.core.config import settings
from app.models import IBClientIdPool


class ClientIdPoolExhausted(RuntimeError):
    pass


def _pool_base(mode: str) -> int:
    base = settings.ib_client_id_pool_base
    if str(mode).lower() == "live":
        base += settings.ib_client_id_live_offset
    return base


def _ensure_pool(session, *, mode: str) -> None:
    base = _pool_base(mode)
    size = settings.ib_client_id_pool_size
    upper = base + size
    existing = {
        row.client_id
        for row in session.query(IBClientIdPool.client_id)
        .filter(and_(IBClientIdPool.client_id >= base, IBClientIdPool.client_id < upper))
        .all()
    }
    missing = [cid for cid in range(base, upper) if cid not in existing]
    if not missing:
        return
    for cid in missing:
        session.add(IBClientIdPool(client_id=cid, status="free"))
    session.commit()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    value = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _read_bridge_heartbeat(output_dir: str | None) -> datetime | None:
    if not output_dir:
        return None
    path = Path(output_dir) / "lean_bridge_status.json"
    if not path.exists():
        return None
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not payload:
        return None
    try:
        data = __import__("json").loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _parse_iso(str(data.get("last_heartbeat") or ""))


def reap_stale_leases(session, *, mode: str, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    base = _pool_base(mode)
    upper = base + settings.ib_client_id_pool_size
    ttl = timedelta(seconds=settings.ib_client_id_lease_ttl_seconds)
    heartbeat_timeout = timedelta(seconds=settings.lean_bridge_heartbeat_timeout_seconds)

    leases = (
        session.query(IBClientIdPool)
        .filter(
            and_(
                IBClientIdPool.client_id >= base,
                IBClientIdPool.client_id < upper,
                IBClientIdPool.status == "leased",
            )
        )
        .all()
    )
    released = 0
    for lease in leases:
        heartbeat = _read_bridge_heartbeat(lease.output_dir)
        lease.last_heartbeat = heartbeat

        acquired = lease.acquired_at or now
        too_old = now - acquired > ttl
        heartbeat_stale = heartbeat is not None and now - heartbeat > heartbeat_timeout
        pid_dead = lease.pid is not None and not _pid_alive(lease.pid)

        if pid_dead or heartbeat_stale or (lease.pid is None and too_old):
            if lease.pid is not None:
                _kill_pid(lease.pid)
            lease.status = "failed"
            lease.released_at = now
            lease.release_reason = "stale_or_dead"
            lease.order_id = None
            lease.pid = None
            lease.output_dir = None
            lease.lease_token = None
            released += 1

    if released:
        session.commit()
    return released


def lease_client_id(session, *, order_id: int, mode: str, output_dir: str) -> IBClientIdPool:
    _ensure_pool(session, mode=mode)
    reap_stale_leases(session, mode=mode)
    base = _pool_base(mode)
    upper = base + settings.ib_client_id_pool_size

    query = session.query(IBClientIdPool).filter(
        and_(
            IBClientIdPool.client_id >= base,
            IBClientIdPool.client_id < upper,
            IBClientIdPool.status != "leased",
        )
    ).order_by(IBClientIdPool.client_id.asc())

    if session.bind and session.bind.dialect.name != "sqlite":
        query = query.with_for_update()

    lease = query.first()
    if lease is None:
        raise ClientIdPoolExhausted("client_id_busy")

    now = datetime.utcnow()
    lease.status = "leased"
    lease.order_id = order_id
    lease.output_dir = output_dir
    lease.lease_token = uuid4().hex
    lease.acquired_at = now
    lease.last_heartbeat = now
    lease.released_at = None
    lease.release_reason = None
    session.commit()
    session.refresh(lease)
    return lease


def attach_lease_pid(session, *, lease_token: str, pid: int) -> None:
    lease = session.query(IBClientIdPool).filter(IBClientIdPool.lease_token == lease_token).first()
    if lease is None:
        return
    lease.pid = pid
    session.commit()
```

**Step 3: 运行测试**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_ib_client_id_pool.py -v`
Expected: PASS

**Step 4: 提交**

```bash
git add backend/app/models.py backend/app/services/ib_client_id_pool.py
git commit -m "feat: add ib client id pool service"
```

---

### Task 3: 支持 execution config 覆盖与异步启动

**Files:**
- Modify: `backend/app/services/lean_execution.py`
- Modify: `backend/tests/test_lean_execution_config.py`
- Modify: `backend/tests/test_lean_execution_runner.py`

**Step 1: 实现可覆盖 client_id/output_dir 与异步启动**

```python
# backend/app/services/lean_execution.py

def build_execution_config(*, intent_path: str, brokerage: str, project_id: int, mode: str,
                           client_id: int | None = None,
                           lean_bridge_output_dir: str | None = None) -> dict:
    payload = dict(_load_template_config())
    payload["environment"] = _resolve_environment(brokerage, mode)
    payload["algorithm-type-name"] = "LeanBridgeExecutionAlgorithm"
    if payload.get("algorithm-type-name") in {"LeanBridgeExecutionAlgorithm", "LeanBridgeSmokeAlgorithm"}:
        payload["algorithm-language"] = "CSharp"
    payload.setdefault("data-folder", "/data/share/stock/data/lean")
    payload["brokerage"] = brokerage
    payload["execution-intent-path"] = intent_path
    payload["result-handler"] = "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
    payload["lean-bridge-output-dir"] = lean_bridge_output_dir or _bridge_output_dir()
    payload["ib-client-id"] = client_id if client_id is not None else derive_client_id(project_id=project_id, mode=mode)
    return payload


def launch_execution_async(*, config_path: str) -> int:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", config_path]
    kwargs: dict[str, object] = {}
    if cwd:
        try:
            sig = inspect.signature(subprocess.Popen)
        except (TypeError, ValueError):
            kwargs["cwd"] = cwd
        else:
            if "cwd" in sig.parameters or any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
            ):
                kwargs["cwd"] = cwd
    process = subprocess.Popen(cmd, **kwargs)
    return process.pid
```

**Step 2: 更新异步启动测试**

```python
# backend/tests/test_lean_execution_runner.py (append)

def test_launch_execution_async_returns_pid(monkeypatch, tmp_path):
    class _FakeProc:
        pid = 123

    def _fake_popen(cmd, cwd=None):
        return _FakeProc()

    monkeypatch.setattr(lean_execution.subprocess, "Popen", _fake_popen)
    pid = lean_execution.launch_execution_async(config_path=str(tmp_path / "exec.json"))
    assert pid == 123
```

**Step 3: 运行测试**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_lean_execution_config.py::test_execution_config_overrides_client_id_and_output_dir -v`
Expected: PASS

Run: `PYTHONPATH=backend pytest -q backend/tests/test_lean_execution_runner.py::test_launch_execution_async_returns_pid -v`
Expected: PASS

**Step 4: 提交**

```bash
git add backend/app/services/lean_execution.py backend/tests/test_lean_execution_config.py backend/tests/test_lean_execution_runner.py
git commit -m "feat: allow execution config overrides and async launch"
```

---

### Task 4: 直连下单接入 client id 池与独立输出目录

**Files:**
- Modify: `backend/app/services/trade_direct_order.py`
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/tests/test_trade_direct_order_client_id_pool.py`

**Step 1: 接入租约分配与 async 启动**

```python
# backend/app/services/trade_direct_order.py (关键片段)
from app.services.ib_client_id_pool import lease_client_id, attach_lease_pid, ClientIdPoolExhausted
from app.services.lean_execution import build_execution_config, launch_execution_async

# 在 submit_direct_order 中
    output_dir = Path(settings.data_root or "/data/share/stock/data") / "lean_bridge" / f"direct_{order.id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        lease = lease_client_id(session, order_id=order.id, mode=mode, output_dir=str(output_dir))
    except ClientIdPoolExhausted as exc:
        raise ValueError("client_id_busy") from exc

    config = build_execution_config(
        intent_path=str(intent_path),
        brokerage="InteractiveBrokersBrokerage",
        project_id=project_id,
        mode=mode,
        client_id=lease.client_id,
        lean_bridge_output_dir=str(output_dir),
    )

    pid = launch_execution_async(config_path=str(config_path))
    attach_lease_pid(session, lease_token=lease.lease_token or "", pid=pid)
```

**Step 2: 更新路由错误映射**

```python
# backend/app/routes/trade.py (direct order handler)
            if detail in {"ib_api_mode_disabled", "ib_settings_missing", "client_id_busy"}:
                raise HTTPException(status_code=409, detail=detail) from exc
```

**Step 3: 运行测试**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_trade_direct_order_client_id_pool.py -v`
Expected: PASS

**Step 4: 提交**

```bash
git add backend/app/services/trade_direct_order.py backend/app/routes/trade.py backend/tests/test_trade_direct_order_client_id_pool.py
git commit -m "feat: use client id pool for direct orders"
```

---

### Task 5: 配置项与数据库补丁

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Create: `deploy/mysql/patches/20260128_ib_client_id_pool.sql`

**Step 1: 新增配置项**

```python
# backend/app/core/config.py
    ib_client_id_pool_base: int = 2000
    ib_client_id_pool_size: int = 32
    ib_client_id_lease_ttl_seconds: int = 300
    lean_bridge_heartbeat_timeout_seconds: int = 60
```

```env
# backend/.env.example (append)
IB_CLIENT_ID_POOL_BASE=2000
IB_CLIENT_ID_POOL_SIZE=32
IB_CLIENT_ID_LEASE_TTL_SECONDS=300
LEAN_BRIDGE_HEARTBEAT_TIMEOUT_SECONDS=60
```

**Step 2: 添加数据库补丁**

```sql
-- deploy/mysql/patches/20260128_ib_client_id_pool.sql
-- Patch: 20260128_ib_client_id_pool
-- Description: Add ib_client_id_pool table for unique client id leasing
-- Impact: Adds new table used by direct order execution
-- Rollback: DROP TABLE ib_client_id_pool;

SET @patch_version = '20260128_ib_client_id_pool';
SET @patch_desc = 'Add ib_client_id_pool table for client id leases';

CREATE TABLE IF NOT EXISTS ib_client_id_pool (
  client_id INT NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'free',
  order_id INT NULL,
  pid INT NULL,
  output_dir VARCHAR(255) NULL,
  lease_token VARCHAR(64) NULL,
  acquired_at DATETIME NULL,
  last_heartbeat DATETIME NULL,
  released_at DATETIME NULL,
  release_reason VARCHAR(255) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- record migration
INSERT IGNORE INTO schema_migrations (version, description, checksum, applied_by)
VALUES (@patch_version, @patch_desc, SHA2(CONCAT(@patch_version, ':', @patch_desc), 256), CURRENT_USER());
```

**Step 3: 运行测试**

Run: `PYTHONPATH=backend pytest -q backend/tests/test_ib_client_id_pool.py -v`
Expected: PASS

**Step 4: 提交**

```bash
git add backend/app/core/config.py backend/.env.example deploy/mysql/patches/20260128_ib_client_id_pool.sql
git commit -m "chore: add ib client id pool settings and migration"
```

---

### Task 6: 全量回归（backend）

**Step 1: 运行**

Run: `PYTHONPATH=backend pytest -q backend/tests`
Expected: PASS (125+ tests)

**Step 2: 提交（如有必要）**

```bash
git status --short
```

