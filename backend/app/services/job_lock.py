from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import fcntl

from app.core.config import settings

DEFAULT_LOCK_TTL_SECONDS = 900
DEFAULT_LOCK_HEARTBEAT_SECONDS = 30


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _resolve_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if raw.isdigit():
        return int(raw)
    return default


def _parse_lock_meta(raw: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class JobLock:
    def __init__(
        self,
        key: str,
        data_root: Path | None = None,
        ttl_seconds: int | None = None,
        heartbeat_interval_seconds: int | None = None,
        auto_heartbeat: bool = True,
    ):
        self.key = key
        self.data_root = data_root or _resolve_data_root()
        self.lock_path = self.data_root / "locks" / f"{key}.lock"
        self._handle = None
        self._owner = ""
        self._host = ""
        self._pid = 0
        self._acquired_at = 0.0
        self._heartbeat_at = 0.0
        self._write_lock = threading.Lock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self.ttl_seconds = ttl_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.auto_heartbeat = auto_heartbeat

    def _resolve_ttl(self) -> int:
        if self.ttl_seconds is not None:
            return max(int(self.ttl_seconds), 0)
        return _resolve_int_env("DATA_LOCK_TTL_SECONDS", DEFAULT_LOCK_TTL_SECONDS)

    def _resolve_heartbeat_interval(self) -> int:
        if self.heartbeat_interval_seconds is not None:
            return max(int(self.heartbeat_interval_seconds), 0)
        return _resolve_int_env(
            "DATA_LOCK_HEARTBEAT_SECONDS", DEFAULT_LOCK_HEARTBEAT_SECONDS
        )

    def _read_metadata(self) -> dict[str, str]:
        if not self.lock_path.exists():
            return {}
        try:
            content = self.lock_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {}
        return _parse_lock_meta(content)

    def _is_stale(self, meta: dict[str, str]) -> bool:
        ttl = int(meta.get("ttl_seconds") or 0)
        if ttl <= 0:
            return False
        heartbeat_raw = meta.get("heartbeat_at") or meta.get("acquired_at") or "0"
        try:
            heartbeat_at = float(heartbeat_raw)
        except ValueError:
            return False
        return (time.time() - heartbeat_at) > ttl

    def _owner_alive(self, meta: dict[str, str]) -> bool:
        host = meta.get("host") or ""
        pid_raw = meta.get("pid") or ""
        if host and host != socket.gethostname():
            return True
        if not pid_raw.isdigit():
            return True
        return _is_pid_alive(int(pid_raw))

    def _write_metadata(self, heartbeat_at: float) -> None:
        if not self._handle:
            return
        ttl = self._resolve_ttl()
        lines = [
            "version=2",
            f"key={self.key}",
            f"owner={self._owner}",
            f"host={self._host}",
            f"pid={self._pid}",
            f"acquired_at={self._acquired_at:.3f}",
            f"heartbeat_at={heartbeat_at:.3f}",
            f"ttl_seconds={ttl}",
        ]
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write("\n".join(lines) + "\n")
        self._handle.flush()

    def _start_heartbeat(self) -> None:
        if not self.auto_heartbeat:
            return
        interval = self._resolve_heartbeat_interval()
        if interval <= 0:
            return
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()

        def _runner() -> None:
            while not self._heartbeat_stop.wait(interval):
                self.heartbeat()

        self._heartbeat_thread = threading.Thread(target=_runner, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1)
        self._heartbeat_thread = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return self._try_recover_stale()
        self._handle = handle
        self._host = socket.gethostname()
        self._pid = os.getpid()
        self._owner = f"{self._host}:{self._pid}"
        self._acquired_at = time.time()
        self._heartbeat_at = self._acquired_at
        with self._write_lock:
            self._write_metadata(self._heartbeat_at)
        self._start_heartbeat()
        return True

    def _try_recover_stale(self) -> bool:
        meta = self._read_metadata()
        if not meta or not self._is_stale(meta):
            return False
        if self._owner_alive(meta):
            return False
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        self._handle = handle
        self._host = socket.gethostname()
        self._pid = os.getpid()
        self._owner = f"{self._host}:{self._pid}"
        self._acquired_at = time.time()
        self._heartbeat_at = self._acquired_at
        with self._write_lock:
            self._write_metadata(self._heartbeat_at)
        self._start_heartbeat()
        return True

    def heartbeat(self) -> bool:
        if not self._handle:
            return False
        with self._write_lock:
            now = time.time()
            self._heartbeat_at = now
            self._write_metadata(now)
        return True

    def release(self) -> None:
        if not self._handle:
            return
        try:
            self._stop_heartbeat()
            fcntl.flock(self._handle, fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self):
        if not self.acquire():
            return None
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
