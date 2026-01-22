from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any

from app.models import DecisionSnapshot, Project
from app.routes.projects import _resolve_project_config
from app.services.project_symbols import collect_project_symbols
from app.services.ib_market import _ib_data_root


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
