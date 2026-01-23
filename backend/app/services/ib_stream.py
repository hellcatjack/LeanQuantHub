from __future__ import annotations

import csv
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Any

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
except Exception:  # pragma: no cover - ibapi optional in some environments
    EClient = object  # type: ignore[assignment]
    EWrapper = object  # type: ignore[assignment]
    Contract = object  # type: ignore[assignment]

from app.models import DecisionSnapshot, Project
from app.routes.projects import _resolve_project_config
from app.services.project_symbols import collect_project_symbols
from app.services.ib_market import _ib_data_root, fetch_market_snapshots
from app.db import SessionLocal
from app.services.ib_settings import get_or_create_ib_settings
from app.services.job_lock import JobLock


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()

_PRICE_TICKS = {1: "bid", 2: "ask", 4: "last", 6: "high", 7: "low", 9: "close"}
_SIZE_TICKS = {0: "bid_size", 3: "ask_size", 5: "last_size", 8: "volume"}


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

CONFIG_FILE = "_config.json"


def write_stream_config(stream_root: Path, payload: dict) -> None:
    stream_root.mkdir(parents=True, exist_ok=True)
    (stream_root / CONFIG_FILE).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_stream_config(stream_root: Path) -> dict:
    path = stream_root / CONFIG_FILE
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_stream_status(
    stream_root: Path,
    *,
    status: str,
    symbols: Iterable[str],
    error: str | None = None,
    market_data_type: str = "delayed",
    degraded_since: str | None = None,
    last_snapshot_refresh: str | None = None,
    source: str | None = None,
) -> dict[str, object]:
    stream_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "last_heartbeat": _utc_now(),
        "subscribed_symbols": sorted({_normalize_symbol(sym) for sym in symbols if _normalize_symbol(sym)}),
        "ib_error_count": 0 if not error else 1,
        "last_error": error,
        "market_data_type": market_data_type,
        "degraded_since": degraded_since,
        "last_snapshot_refresh": last_snapshot_refresh,
        "source": source,
    }
    (stream_root / "_status.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def get_stream_status(data_root: Path | str | None = None) -> dict[str, object]:
    stream_root = None
    if data_root is not None:
        candidate = Path(data_root)
        if (candidate / "_status.json").exists():
            stream_root = candidate
    if stream_root is None:
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
            "degraded_since": None,
            "last_snapshot_refresh": None,
            "source": None,
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
            "degraded_since": None,
            "last_snapshot_refresh": None,
            "source": None,
        }
    return {
        "status": payload.get("status") or "unknown",
        "last_heartbeat": payload.get("last_heartbeat"),
        "subscribed_symbols": payload.get("subscribed_symbols") or [],
        "ib_error_count": int(payload.get("ib_error_count") or 0),
        "last_error": payload.get("last_error"),
        "market_data_type": payload.get("market_data_type") or "delayed",
        "degraded_since": payload.get("degraded_since"),
        "last_snapshot_refresh": payload.get("last_snapshot_refresh"),
        "source": payload.get("source"),
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


class IBStreamClient(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, on_tick) -> None:
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._on_tick = on_tick
        self._thread: threading.Thread | None = None
        self._req_id = 1
        self._req_map: dict[int, str] = {}
        self._error: str | None = None

    def start(self) -> None:
        self.connect(self._host, int(self._port), int(self._client_id))
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.isConnected():
            self.disconnect()

    def subscribe(self, symbols: list[str]) -> None:
        for symbol in symbols:
            req_id = self._req_id
            self._req_id += 1
            contract = Contract()
            contract.symbol = _normalize_symbol(symbol)
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            self._req_map[req_id] = _normalize_symbol(symbol)
            self.reqMktData(req_id, contract, "", False, False, [])

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802
        key = _PRICE_TICKS.get(tickType)
        symbol = self._req_map.get(reqId)
        if key and symbol:
            self._on_tick(symbol, {key: price})

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802
        key = _SIZE_TICKS.get(tickType)
        symbol = self._req_map.get(reqId)
        if key and symbol:
            self._on_tick(symbol, {key: size})

class IBStreamRunner:
    def __init__(
        self,
        *,
        project_id: int,
        decision_snapshot_id: int | None = None,
        refresh_interval_seconds: int = 60,
        stale_seconds: int = 15,
        max_symbols: int | None = None,
        data_root: Path | str | None = None,
        api_mode: str = "ib",
    ) -> None:
        self.project_id = project_id
        self.decision_snapshot_id = decision_snapshot_id
        self.refresh_interval_seconds = refresh_interval_seconds
        self.stale_seconds = stale_seconds
        self.max_symbols = max_symbols
        self.api_mode = api_mode
        self._stream_root = _resolve_stream_root(data_root)
        self._last_tick_ts: dict[str, datetime] = {}
        self._degraded_since: str | None = None
        self._last_snapshot_refresh: str | None = None
        self._client: IBStreamClient | None = None
        self._subscribed_symbols: list[str] = []

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

    def _handle_tick(self, symbol: str, tick: dict[str, Any], *, source: str = "ib_stream") -> None:
        symbol = _normalize_symbol(symbol)
        self._last_tick_ts[symbol] = datetime.utcnow()
        self._write_tick(symbol, tick, source=source)

    def _refresh_snapshot_if_stale(self, symbols: list[str]) -> None:
        now = datetime.utcnow()
        stale: list[str] = []
        for symbol in symbols:
            norm = _normalize_symbol(symbol)
            last = self._last_tick_ts.get(norm)
            if last is None or (now - last) > timedelta(seconds=int(self.stale_seconds or 0)):
                stale.append(norm)
        if not stale:
            return
        session = SessionLocal()
        try:
            snapshots = fetch_market_snapshots(session, symbols=stale, store=False)
        finally:
            session.close()
        for item in snapshots:
            symbol = item.get("symbol")
            payload = item.get("data") or {}
            if symbol:
                self._handle_tick(symbol, payload, source="ib_snapshot")
        if self._degraded_since is None:
            self._degraded_since = _utc_now()
        self._last_snapshot_refresh = _utc_now()

    def _write_status_update(
        self,
        symbols: list[str],
        *,
        market_data_type: str,
        status: str = "connected",
        error: str | None = None,
    ) -> dict[str, object]:
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

    def _ensure_symbols(self, symbols: list[str]) -> list[str]:
        if symbols:
            return symbols
        if not self.project_id:
            return []
        session = SessionLocal()
        try:
            return build_stream_symbols(
                session,
                project_id=self.project_id,
                decision_snapshot_id=self.decision_snapshot_id,
                max_symbols=self.max_symbols,
            )
        finally:
            session.close()

    def _ensure_client(self, settings, symbols: list[str]) -> None:
        if self.api_mode == "mock":
            return
        if self._client is None:
            self._client = IBStreamClient(settings.host, settings.port, settings.client_id, self._handle_tick)
            self._client.start()
        if symbols and set(symbols) != set(self._subscribed_symbols):
            self._client.subscribe(symbols)
            self._subscribed_symbols = list(symbols)

    def run_forever(self) -> None:
        while True:
            config = read_stream_config(self._stream_root)
            if not config:
                self._write_status_update([], market_data_type="delayed", status="disconnected")
                time.sleep(10)
                continue
            if config.get("enabled") is False:
                self._write_status_update([], market_data_type="delayed", status="stopped")
                time.sleep(10)
                continue

            self.project_id = config.get("project_id") or self.project_id
            self.decision_snapshot_id = config.get("decision_snapshot_id") or self.decision_snapshot_id
            self.max_symbols = config.get("max_symbols") or self.max_symbols
            self.refresh_interval_seconds = config.get("refresh_interval_seconds") or self.refresh_interval_seconds
            self.stale_seconds = config.get("stale_seconds") or self.stale_seconds
            market_data_type = config.get("market_data_type") or "delayed"

            symbols = self._ensure_symbols(config.get("symbols") or [])
            session = SessionLocal()
            try:
                settings = get_or_create_ib_settings(session)
                self.api_mode = getattr(settings, "api_mode", self.api_mode) or self.api_mode
                self._ensure_client(settings, symbols)
                self._refresh_snapshot_if_stale(symbols)
                status = "degraded" if self._degraded_since else "connected"
                self._write_status_update(symbols, market_data_type=market_data_type, status=status)
            finally:
                session.close()

            time.sleep(max(1, int(self.refresh_interval_seconds or 5)))

    def write_status(self, status: str, symbols: list[str], market_data_type: str) -> dict[str, object]:
        return write_stream_status(
            self._stream_root,
            status=status,
            symbols=symbols,
            market_data_type=market_data_type,
        )

    def read_status(self) -> dict[str, object]:
        return get_stream_status(self._stream_root.parent)
