from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.services.lean_bridge_reader import read_quotes


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _ib_data_root() -> Path:
    root = _resolve_data_root() / "ib"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_bridge_root() -> Path:
    base = settings.data_root or settings.artifact_root
    return Path(base) / "lean_bridge"


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _quote_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    payload = item.get("data") if isinstance(item.get("data"), dict) else item
    return payload if isinstance(payload, dict) else None


def _quote_timestamp(item: dict[str, Any], fallback: str | None) -> str | None:
    if not isinstance(item, dict):
        return fallback
    ts = item.get("timestamp")
    if isinstance(ts, str) and ts.strip():
        return ts
    payload = item.get("data") if isinstance(item.get("data"), dict) else None
    if isinstance(payload, dict):
        ts = payload.get("timestamp")
        if isinstance(ts, str) and ts.strip():
            return ts
    return fallback


@contextmanager
def ib_request_lock(wait_seconds: float = 0.0, retry_interval: float = 0.2) -> Any:
    yield


def fetch_market_snapshots(
    _session,
    *,
    symbols: Iterable[str],
    store: bool = False,
    market_data_type: str | None = None,
    fallback_history: bool = False,
    history_duration: str | None = None,
    history_bar_size: str | None = None,
    history_use_rth: bool | None = None,
) -> list[dict[str, Any]]:
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    stale = bool(quotes.get("stale", False))
    updated_at = quotes.get("updated_at") or quotes.get("refreshed_at")
    by_symbol = {
        _normalize_symbol(item.get("symbol")): item
        for item in items
        if isinstance(item, dict) and _normalize_symbol(item.get("symbol"))
    }
    results: list[dict[str, Any]] = []
    for symbol in symbols:
        normalized = _normalize_symbol(symbol)
        item = by_symbol.get(normalized)
        if not item:
            results.append({"symbol": normalized, "data": None, "error": "quote_missing"})
            continue
        payload = _quote_payload(item)
        if not payload:
            results.append({"symbol": normalized, "data": None, "error": "quote_invalid"})
            continue
        if stale:
            results.append({"symbol": normalized, "data": payload, "error": "stale"})
            continue
        timestamp = _quote_timestamp(item, updated_at)
        if timestamp:
            payload.setdefault("timestamp", timestamp)
        results.append({"symbol": normalized, "data": payload, "error": None})
    return results


def check_market_health(
    session,
    *,
    symbols: Iterable[str],
    min_success_ratio: float = 1.0,
    fallback_history: bool = False,
    history_duration: str | None = None,
    history_bar_size: str | None = None,
    history_use_rth: bool | None = None,
) -> dict[str, Any]:
    items = fetch_market_snapshots(session, symbols=symbols, store=False)
    total = len(items)
    success = sum(1 for item in items if item.get("data") and not item.get("error"))
    missing = [item.get("symbol") for item in items if item.get("error")]
    ratio = (success / total) if total else 0.0
    status = "ok" if total and ratio >= float(min_success_ratio) else "degraded"
    errors = [str(item.get("error")) for item in items if item.get("error")]
    return {
        "status": status if total else "blocked",
        "total": total,
        "success": success,
        "missing_symbols": [sym for sym in missing if sym],
        "errors": errors,
    }


def refresh_contract_cache(
    _session,
    *,
    symbols: list[str] | None = None,
    sec_type: str | None = None,
    exchange: str | None = None,
    currency: str | None = None,
    use_project_symbols: bool = False,
) -> dict[str, Any]:
    return {
        "total": 0,
        "updated": 0,
        "skipped": 0,
        "errors": ["unsupported"],
        "duration_sec": 0.0,
    }


def fetch_historical_bars(
    _session,
    *,
    symbol: str,
    duration: str,
    bar_size: str,
    end_datetime: str | None = None,
    use_rth: bool = True,
    store: bool = True,
) -> dict[str, Any]:
    return {"symbol": _normalize_symbol(symbol), "bars": 0, "path": None, "error": "unsupported"}
