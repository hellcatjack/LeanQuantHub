from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import func

from app.core.config import settings
from app.models import LeanExecutorPool
from app.services.job_lock import JobLock
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import parse_bridge_timestamp, read_bridge_status
from app.services.lean_bridge_watchlist import refresh_leader_watchlist
_DEFAULT_LAUNCHER_DIR = Path("/app/stocklean/Lean_git/Launcher/bin/Release")


def _resolve_launcher() -> tuple[str, str | None]:
    dll_setting = str(settings.lean_launcher_dll or "").strip()
    launcher_path = str(settings.lean_launcher_path or "").strip()

    launcher_dir: Path | None = None
    if launcher_path:
        launcher_candidate = Path(launcher_path)
        if launcher_candidate.exists() and launcher_candidate.is_file():
            launcher_dir = launcher_candidate.parent
        else:
            launcher_dir = launcher_candidate

    if dll_setting:
        dll_path = Path(dll_setting)
        if not dll_path.is_absolute() and launcher_dir is not None:
            dll_path = launcher_dir / dll_path
        cwd = str(dll_path.parent) if dll_path.is_absolute() else (str(launcher_dir) if launcher_dir is not None else None)
        return str(dll_path), cwd

    if launcher_dir is not None:
        dll_path = launcher_dir / "QuantConnect.Lean.Launcher.dll"
        if not dll_path.exists():
            candidate = launcher_dir / "bin" / "Release" / "QuantConnect.Lean.Launcher.dll"
            if candidate.exists():
                return str(candidate), str(candidate.parent)
        return str(dll_path), str(launcher_dir)

    dll_path = _DEFAULT_LAUNCHER_DIR / "QuantConnect.Lean.Launcher.dll"
    return str(dll_path), str(_DEFAULT_LAUNCHER_DIR)


def _build_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    if settings.dotnet_root:
        env["DOTNET_ROOT"] = settings.dotnet_root
        env["PATH"] = f"{settings.dotnet_root}:{env.get('PATH', '')}"
    if settings.python_dll:
        env["PYTHONNET_PYDLL"] = settings.python_dll
    if settings.lean_python_venv:
        env["PYTHONHOME"] = settings.lean_python_venv
    return env

_LEADER_LOCK_KEY = "lean_bridge_leader"
_LEADER_THREAD: threading.Thread | None = None
_LEADER_STOP = threading.Event()
_LEADER_CHECK_SECONDS = 5


def _bridge_root() -> Path:
    return resolve_bridge_root()


def _state_path() -> Path:
    return _bridge_root() / "bridge_process.json"


def _read_state() -> dict:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(*, pid: int, config_path: Path, mode: str, client_id: int) -> None:
    payload = {
        "pid": int(pid),
        "config_path": str(config_path),
        "mode": mode,
        "client_id": client_id,
        "started_at": datetime.utcnow().isoformat() + "Z",
    }
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_pid(pid: int | None) -> None:
    if not pid or pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _heartbeat_stale(payload: dict, *, timeout_seconds: int) -> bool:
    if payload.get("status") == "missing":
        return True
    heartbeat = parse_bridge_timestamp(payload, ["last_heartbeat", "updated_at"])
    if heartbeat is None:
        return True
    now = datetime.now(timezone.utc)
    return now - heartbeat > timedelta(seconds=timeout_seconds)


def _parse_started_at(state: dict | None) -> datetime | None:
    if not isinstance(state, dict):
        return None
    return parse_bridge_timestamp(state, ["started_at"])


def _within_startup_grace(state: dict | None, *, now: datetime | None, timeout_seconds: int) -> bool:
    started_at = _parse_started_at(state)
    if started_at is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    return now - started_at <= timedelta(seconds=timeout_seconds)


def _should_restart(status: dict, state: dict | None, *, timeout_seconds: int, now: datetime | None) -> bool:
    pid = 0
    if isinstance(state, dict):
        try:
            pid = int(state.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
    if not _pid_alive(pid):
        return True
    stale = _heartbeat_stale(status, timeout_seconds=timeout_seconds)
    if not stale:
        return False
    if _within_startup_grace(state, now=now, timeout_seconds=timeout_seconds):
        return False
    return True


def _write_watchlist(session) -> Path:
    root = _bridge_root()
    # IB accounts have a market data subscription cap. Keep the leader watchlist small and
    # prioritize positions/active intents/latest snapshots plus risk-off symbols.
    refresh_leader_watchlist(session, max_symbols=100, bridge_root=root)
    return root / "watchlist.json"


def _load_template_config(mode: str) -> dict:
    template = Path("/app/stocklean/Lean_git/Launcher/config-lean-bridge-live-paper.json")
    if template.exists():
        try:
            payload = json.loads(template.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            return payload
    return {
        "algorithm-language": "CSharp",
        "algorithm-type-name": "LeanBridgeSmokeAlgorithm",
        "environment": "live-interactive",
        "brokerage": "InteractiveBrokersBrokerage",
    }


def _resolve_leader_client_id(settings_row, *, mode: str) -> int:
    if settings_row and getattr(settings_row, "client_id", None):
        try:
            return int(settings_row.client_id)
        except (TypeError, ValueError):
            pass
    base = settings.ib_client_id_pool_base
    if str(mode).lower() == "live":
        base += settings.ib_client_id_live_offset
    return base


def _build_leader_config(session, *, mode: str, watchlist_path: Path) -> tuple[dict, int]:
    from app.services.ib_settings import get_or_create_ib_settings

    settings_row = get_or_create_ib_settings(session)
    payload = dict(_load_template_config(mode))
    client_id = _resolve_leader_client_id(settings_row, mode=mode)
    payload["algorithm-type-name"] = "LeanBridgeSmokeAlgorithm"
    payload["brokerage"] = "InteractiveBrokersBrokerage"
    # Prevent Lean console launcher from blocking on "Press any key to continue." if it ever exits.
    payload.setdefault("close-automatically", True)
    payload.setdefault("data-folder", "/data/share/stock/data/lean")
    payload["ib-host"] = settings_row.host
    payload["ib-port"] = int(settings_row.port)
    payload["ib-client-id"] = client_id
    payload["ib-trading-mode"] = mode
    payload["lean-bridge-output-dir"] = str(_bridge_root())
    payload["lean-bridge-watchlist-path"] = str(watchlist_path)
    payload.setdefault("lean-bridge-heartbeat-seconds", "2")
    payload.setdefault("lean-bridge-watchlist-refresh-seconds", "5")
    payload.setdefault("lean-bridge-snapshot-seconds", "2")
    payload.setdefault("lean-bridge-open-orders-seconds", "10")
    return payload, client_id


def _launch_leader(config_path: Path) -> int:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", str(config_path)]
    proc = subprocess.Popen(cmd, cwd=cwd, env=_build_launch_env())
    return int(proc.pid)


def _upsert_leader_pool(
    session,
    *,
    mode: str,
    client_id: int,
    pid: int | None,
    status_payload: dict,
) -> None:
    if session is None:
        return
    row = (
        session.query(LeanExecutorPool)
        .filter(LeanExecutorPool.mode == mode, LeanExecutorPool.role == "leader")
        .first()
    )
    if row is None:
        pool_kwargs = {"mode": mode, "role": "leader", "client_id": client_id}
        if session.bind and session.bind.dialect.name == "sqlite":
            next_id = (session.query(func.max(LeanExecutorPool.id)).scalar() or 0) + 1
            pool_kwargs["id"] = int(next_id)
        row = LeanExecutorPool(**pool_kwargs)
        session.add(row)
    row.client_id = client_id
    row.pid = pid
    row.status = str(status_payload.get("status") or "unknown")
    row.output_dir = str(_bridge_root())
    row.last_error = status_payload.get("last_error")
    row.last_heartbeat = parse_bridge_timestamp(status_payload, ["last_heartbeat", "updated_at"])
    session.commit()


def ensure_lean_bridge_leader(session, *, mode: str, force: bool = False) -> dict:
    mode = str(mode or "paper").strip().lower() or "paper"
    root = _bridge_root()
    status = read_bridge_status(root)
    timeout = int(settings.lean_bridge_heartbeat_timeout_seconds)
    state = _read_state()
    pid = int(state.get("pid") or 0)
    now = datetime.now(timezone.utc)
    restart = force or _should_restart(status, state, timeout_seconds=timeout, now=now)
    if not restart and _pid_alive(pid):
        _upsert_leader_pool(
            session,
            mode=mode,
            client_id=int(state.get("client_id") or 0),
            pid=pid,
            status_payload=status,
        )
        return status

    lock = JobLock(_LEADER_LOCK_KEY, data_root=root)
    if not lock.acquire():
        return status
    try:
        status = read_bridge_status(root)
        state = _read_state()
        pid = int(state.get("pid") or 0)
        now = datetime.now(timezone.utc)
        restart = force or _should_restart(status, state, timeout_seconds=timeout, now=now)
        if not restart and _pid_alive(pid):
            _upsert_leader_pool(
                session,
                mode=mode,
                client_id=int(state.get("client_id") or 0),
                pid=pid,
                status_payload=status,
            )
            return status

        if _pid_alive(pid):
            _terminate_pid(pid)

        watchlist_path = _write_watchlist(session)
        payload, client_id = _build_leader_config(session, mode=mode, watchlist_path=watchlist_path)
        config_dir = Path(settings.artifact_root) / "lean_bridge"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"lean_bridge_{mode}.json"
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        pid = _launch_leader(config_path)
        _write_state(pid=pid, config_path=config_path, mode=mode, client_id=client_id)
        status = read_bridge_status(root)
        _upsert_leader_pool(session, mode=mode, client_id=client_id, pid=pid, status_payload=status)
        return status
    finally:
        lock.release()


def start_leader_watchdog(session_factory) -> None:
    global _LEADER_THREAD
    if _LEADER_THREAD and _LEADER_THREAD.is_alive():
        return
    _LEADER_STOP.clear()

    def _runner() -> None:
        from app.services.ib_settings import get_or_create_ib_settings

        while not _LEADER_STOP.wait(_LEADER_CHECK_SECONDS):
            try:
                with session_factory() as session:
                    settings_row = get_or_create_ib_settings(session)
                    mode = str(settings_row.mode or "paper").strip().lower() or "paper"
                    ensure_lean_bridge_leader(session, mode=mode)
            except Exception:
                continue

    _LEADER_THREAD = threading.Thread(target=_runner, daemon=True)
    _LEADER_THREAD.start()
