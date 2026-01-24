from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
import time

from app.db import get_session
from app.services import ib_stream
from app.services.ib_market import fetch_market_snapshots
from app.services.ib_settings import update_ib_state


class StreamSnapshotWriter:
    def __init__(self, stream_root: Path) -> None:
        self.stream_root = stream_root
        self.stream_root.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, symbol: str, payload: dict) -> None:
        symbol = str(symbol or "").strip().upper()
        path = self.stream_root / f"{symbol}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class StreamStatusWriter:
    def __init__(self, stream_root: Path) -> None:
        self.stream_root = stream_root
        self.stream_root.mkdir(parents=True, exist_ok=True)

    def write_status(
        self,
        *,
        status: str,
        symbols: list[str],
        error: str | None,
        market_data_type: str,
    ) -> None:
        payload = {
            "status": status,
            "last_heartbeat": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "subscribed_symbols": sorted({str(sym or "").strip().upper() for sym in symbols}),
            "ib_error_count": 0 if not error else 1,
            "last_error": error,
            "market_data_type": market_data_type,
        }
        (self.stream_root / "_status.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


@dataclass
class StreamRunConfig:
    stream_root: Path
    symbols: list[str]
    market_data_type: str
    refresh_interval_seconds: int = 60
    fallback_history: bool = True
    history_duration: str = "5 D"
    history_bar_size: str = "1 day"
    history_use_rth: bool = True


_stream_thread: threading.Thread | None = None
_stream_stop = threading.Event()


def _normalize_symbols(raw: list[str] | None) -> list[str]:
    items = []
    for symbol in raw or []:
        value = str(symbol or "").strip().upper()
        if value:
            items.append(value)
    return sorted(set(items))


def _resolve_run_config(session, stream_root: Path) -> StreamRunConfig | None:
    config = ib_stream.read_stream_config(stream_root)
    if not isinstance(config, dict) or not config:
        return None
    if not config.get("enabled", False):
        return None
    market_data_type = (config.get("market_data_type") or "delayed").strip().lower()
    refresh_interval = config.get("refresh_interval_seconds") or 60
    try:
        refresh_interval = max(5, int(refresh_interval))
    except (TypeError, ValueError):
        refresh_interval = 60
    symbols = _normalize_symbols(config.get("symbols"))
    if not symbols:
        project_id = config.get("project_id")
        if project_id:
            symbols = ib_stream.build_stream_symbols(
                session,
                project_id=int(project_id),
                decision_snapshot_id=config.get("decision_snapshot_id"),
                max_symbols=config.get("max_symbols"),
            )
    return StreamRunConfig(
        stream_root=stream_root,
        symbols=symbols,
        market_data_type=market_data_type,
        refresh_interval_seconds=refresh_interval,
    )


def _write_snapshots(writer: StreamSnapshotWriter, results: list[dict]) -> str | None:
    error: str | None = None
    for item in results:
        symbol = str(item.get("symbol") or "").strip().upper()
        payload = item.get("data")
        if not symbol or not isinstance(payload, dict):
            if item.get("error") and not error:
                error = str(item.get("error"))
            continue
        payload = dict(payload)
        payload.setdefault("symbol", symbol)
        writer.write_snapshot(symbol, payload)
        if item.get("error") and not error:
            error = str(item.get("error"))
    return error


def run_stream_loop(*, data_root: Path | str | None = None) -> None:
    stream_root = ib_stream._resolve_stream_root(data_root)
    lock = ib_stream.acquire_stream_lock(stream_root.parent)
    try:
        with get_session() as session:
            status_writer = StreamStatusWriter(stream_root)
            snapshot_writer = StreamSnapshotWriter(stream_root)
            while not _stream_stop.is_set():
                run_config = _resolve_run_config(session, stream_root)
                if run_config is None:
                    status_writer.write_status(
                        status="stopped",
                        symbols=[],
                        error=None,
                        market_data_type="delayed",
                    )
                    update_ib_state(session, status="disconnected", message="stream_stopped")
                    break
                if not run_config.symbols:
                    status_writer.write_status(
                        status="degraded",
                        symbols=[],
                        error="symbols_empty",
                        market_data_type=run_config.market_data_type,
                    )
                    update_ib_state(session, status="degraded", message="symbols_empty")
                    time.sleep(run_config.refresh_interval_seconds)
                    continue
                try:
                    results = fetch_market_snapshots(
                        session,
                        symbols=run_config.symbols,
                        store=False,
                        market_data_type=run_config.market_data_type,
                        fallback_history=run_config.fallback_history,
                        history_duration=run_config.history_duration,
                        history_bar_size=run_config.history_bar_size,
                        history_use_rth=run_config.history_use_rth,
                    )
                    error = _write_snapshots(snapshot_writer, results)
                    status = "connected" if not error else "degraded"
                    status_writer.write_status(
                        status=status,
                        symbols=run_config.symbols,
                        error=error,
                        market_data_type=run_config.market_data_type,
                    )
                    update_ib_state(
                        session,
                        status=status,
                        message=error or "stream_ok",
                    )
                except RuntimeError as exc:
                    status_writer.write_status(
                        status="degraded",
                        symbols=run_config.symbols,
                        error=str(exc),
                        market_data_type=run_config.market_data_type,
                    )
                    update_ib_state(session, status="degraded", message=str(exc))
                time.sleep(run_config.refresh_interval_seconds)
    finally:
        lock.release()


def start_stream_daemon(*, data_root: Path | str | None = None) -> bool:
    global _stream_thread
    if _stream_thread and _stream_thread.is_alive():
        return False
    _stream_stop.clear()
    _stream_thread = threading.Thread(
        target=run_stream_loop,
        kwargs={"data_root": data_root},
        daemon=True,
    )
    _stream_thread.start()
    return True


def stop_stream_daemon() -> None:
    _stream_stop.set()
