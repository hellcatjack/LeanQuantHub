from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any, Callable
import threading
import time

from app.db import get_session
from app.models import DecisionSnapshot, Project
from app.routes.projects import _resolve_project_config
from app.services.project_symbols import collect_project_symbols
from app.services.ib_market import _ib_data_root, fetch_market_snapshots
from app.services.job_lock import JobLock

_STREAM_THREAD: threading.Thread | None = None
_STREAM_LOCK = threading.Lock()


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _read_snapshot_symbols(path: str | None) -> list[str]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    symbols: set[str] = set()
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = _normalize_symbol(row.get("symbol"))
            if symbol:
                symbols.add(symbol)
    return sorted(symbols)


def _clip_symbols(symbols: Iterable[str], max_symbols: int | None) -> list[str]:
    items = sorted({_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)})
    if max_symbols is not None:
        try:
            limit = max(0, int(max_symbols))
        except (TypeError, ValueError):
            limit = None
        if limit:
            return items[:limit]
    return items


def _collect_project_symbols(session, project_id: int) -> list[str]:
    project = session.get(Project, project_id)
    if not project:
        return []
    config = _resolve_project_config(session, project_id)
    return collect_project_symbols(config)


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _resolve_stream_root(data_root: Path | str | None) -> Path:
    root = Path(data_root) if data_root is not None else _ib_data_root()
    stream_root = root / "stream"
    stream_root.mkdir(parents=True, exist_ok=True)
    return stream_root


def _default_source(api_mode: str) -> str:
    return "mock" if api_mode == "mock" else "ib_stream"


def acquire_stream_lock(data_root: Path | str | None = None) -> JobLock:
    lock_root = Path(data_root) if data_root is not None else None
    lock = JobLock("ib_stream", lock_root)
    if not lock.acquire():
        raise RuntimeError("ib_stream_lock_busy")
    return lock


@contextmanager
def stream_lock(data_root: Path | str | None = None) -> Any:
    lock = acquire_stream_lock(data_root)
    try:
        yield lock
    finally:
        lock.release()


def write_stream_status(
    stream_root: Path,
    *,
    status: str,
    symbols: Iterable[str],
    error: str | None = None,
    market_data_type: str = "delayed",
) -> dict[str, object]:
    stream_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "last_heartbeat": _utc_now(),
        "subscribed_symbols": sorted({_normalize_symbol(sym) for sym in symbols if _normalize_symbol(sym)}),
        "ib_error_count": 0 if not error else 1,
        "last_error": error,
        "market_data_type": market_data_type,
    }
    (stream_root / "_status.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def get_stream_status(data_root: Path | str | None = None) -> dict[str, object]:
    stream_root = _resolve_stream_root(data_root)
    status_path = stream_root / "_status.json"
    if not status_path.exists():
        return {
            "status": "disconnected",
            "last_heartbeat": None,
            "subscribed_symbols": [],
            "ib_error_count": 0,
            "last_error": None,
            "market_data_type": "delayed",
        }
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "status": "degraded",
            "last_heartbeat": None,
            "subscribed_symbols": [],
            "ib_error_count": 1,
            "last_error": "invalid_status_json",
            "market_data_type": "delayed",
        }
    return {
        "status": payload.get("status") or "unknown",
        "last_heartbeat": payload.get("last_heartbeat"),
        "subscribed_symbols": payload.get("subscribed_symbols") or [],
        "ib_error_count": int(payload.get("ib_error_count") or 0),
        "last_error": payload.get("last_error"),
        "market_data_type": payload.get("market_data_type") or "delayed",
    }


def build_stream_symbols(
    session,
    *,
    project_id: int,
    decision_snapshot_id: int | None = None,
    max_symbols: int | None = None,
) -> list[str]:
    if decision_snapshot_id:
        snapshot = session.get(DecisionSnapshot, decision_snapshot_id)
        if snapshot:
            symbols = _read_snapshot_symbols(snapshot.items_path)
            if symbols:
                return _clip_symbols(symbols, max_symbols)
    return _clip_symbols(_collect_project_symbols(session, project_id), max_symbols)


class IBStreamRunner:
    def __init__(
        self,
        *,
        project_id: int,
        decision_snapshot_id: int | None = None,
        refresh_interval_seconds: int = 60,
        max_symbols: int | None = None,
        data_root: Path | str | None = None,
        api_mode: str = "ib",
    ) -> None:
        self.project_id = project_id
        self.decision_snapshot_id = decision_snapshot_id
        self.refresh_interval_seconds = refresh_interval_seconds
        self.max_symbols = max_symbols
        self.api_mode = api_mode
        self._stream_root = _resolve_stream_root(data_root)

    def _write_tick(self, symbol: str, tick: dict[str, Any], source: str | None = None) -> dict[str, Any]:
        symbol = _normalize_symbol(symbol)
        payload: dict[str, Any] = {
            "symbol": symbol,
            "timestamp": _utc_now(),
            "source": source or _default_source(self.api_mode),
        }
        for key, value in (tick or {}).items():
            if value is not None:
                payload[key] = value
        (self._stream_root / f"{symbol}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload


def run_stream_once(
    *,
    project_id: int,
    decision_snapshot_id: int | None,
    symbols: list[str] | None,
    max_symbols: int | None,
    data_root: Path | str | None,
    api_mode: str,
    market_data_type: str,
    fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    session_factory: Callable[[], Any] = get_session,
) -> dict[str, Any]:
    fetch_fn = fetcher or fetch_market_snapshots
    with session_factory() as session:
        if not symbols:
            symbols = build_stream_symbols(
                session,
                project_id=project_id,
                decision_snapshot_id=decision_snapshot_id,
                max_symbols=max_symbols,
            )
        symbols = [_normalize_symbol(sym) for sym in (symbols or []) if _normalize_symbol(sym)]
        if not symbols:
            return {"symbols": [], "errors": ["symbols_empty"], "count": 0}
        results = fetch_fn(
            session,
            symbols=symbols,
            store=False,
            fallback_history=True,
            history_duration="5 D",
            history_bar_size="1 day",
            history_use_rth=True,
        )
    runner = IBStreamRunner(
        project_id=project_id,
        decision_snapshot_id=decision_snapshot_id,
        max_symbols=max_symbols,
        data_root=data_root,
        api_mode=api_mode,
    )
    errors: list[str] = []
    for item in results:
        symbol = _normalize_symbol(item.get("symbol") or "")
        if not symbol:
            continue
        payload = item.get("data") or {}
        error = item.get("error")
        if payload:
            runner._write_tick(symbol, payload, source=payload.get("source"))  # noqa: SLF001
        if error:
            errors.append(f"{symbol}:{error}")
    return {"symbols": symbols, "errors": errors, "count": len(results), "market_data_type": market_data_type}


def run_stream_loop(
    *,
    project_id: int,
    decision_snapshot_id: int | None,
    symbols: list[str] | None,
    max_symbols: int | None,
    refresh_interval_seconds: int,
    data_root: Path | str | None,
    api_mode: str,
    market_data_type: str,
) -> None:
    stream_root = _resolve_stream_root(data_root)
    try:
        with stream_lock(data_root):
            status = write_stream_status(
                stream_root,
                status="running",
                symbols=symbols or [],
                market_data_type=market_data_type,
            )
            while True:
                current = get_stream_status(data_root)
                if current.get("status") in {"stopped", "error"}:
                    break
                result = run_stream_once(
                    project_id=project_id,
                    decision_snapshot_id=decision_snapshot_id,
                    symbols=symbols,
                    max_symbols=max_symbols,
                    data_root=data_root,
                    api_mode=api_mode,
                    market_data_type=market_data_type,
                )
                errors = result.get("errors") or []
                status = write_stream_status(
                    stream_root,
                    status="running",
                    symbols=result.get("symbols") or [],
                    error=errors[-1] if errors else None,
                    market_data_type=market_data_type,
                )
                time.sleep(max(1, int(refresh_interval_seconds)))
    except Exception as exc:
        write_stream_status(
            stream_root,
            status="error",
            symbols=symbols or [],
            error=str(exc),
            market_data_type=market_data_type,
        )
        raise


def start_stream(
    *,
    project_id: int,
    decision_snapshot_id: int | None,
    symbols: list[str] | None,
    max_symbols: int | None,
    refresh_interval_seconds: int = 60,
    data_root: Path | str | None = None,
    api_mode: str = "ib",
    market_data_type: str = "delayed",
) -> threading.Thread | None:
    global _STREAM_THREAD
    with _STREAM_LOCK:
        if _STREAM_THREAD and _STREAM_THREAD.is_alive():
            return None
        thread = threading.Thread(
            target=run_stream_loop,
            kwargs={
                "project_id": project_id,
                "decision_snapshot_id": decision_snapshot_id,
                "symbols": symbols,
                "max_symbols": max_symbols,
                "refresh_interval_seconds": refresh_interval_seconds,
                "data_root": data_root,
                "api_mode": api_mode,
                "market_data_type": market_data_type,
            },
            daemon=True,
        )
        _STREAM_THREAD = thread
        thread.start()
        return thread
