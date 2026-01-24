from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from app.models import DecisionSnapshot, Project
from app.routes.projects import _resolve_project_config
from app.services.lean_bridge import CACHE_ROOT
from app.services.project_symbols import collect_project_symbols


def normalize_symbol(symbol: str | None) -> str:
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
            symbol = normalize_symbol(row.get("symbol"))
            if symbol:
                symbols.add(symbol)
    return sorted(symbols)


def _clip_symbols(symbols: Iterable[str], max_symbols: int | None) -> list[str]:
    items = sorted({normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)})
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


def build_market_symbols(
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


def _read_quotes() -> list[dict[str, Any]]:
    path = CACHE_ROOT / "quotes.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def fetch_market_snapshots(
    session,
    *,
    symbols: list[str],
    store: bool,
    fallback_history: bool,
    history_duration: str,
    history_bar_size: str,
    history_use_rth: bool,
) -> list[dict[str, Any]]:
    quote_list = _read_quotes()
    quote_map = {normalize_symbol(item.get("symbol")): item for item in quote_list}
    items: list[dict[str, Any]] = []
    for symbol in symbols:
        key = normalize_symbol(symbol)
        quote = quote_map.get(key)
        if quote:
            items.append({"symbol": key, "data": quote, "error": None})
        else:
            items.append({"symbol": key, "data": None, "error": "quote_missing"})
    return items


def is_snapshot_fresh(symbols: Iterable[str], ttl_seconds: int | None) -> bool:
    if ttl_seconds is None:
        return False
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        return False
    if ttl <= 0:
        return False
    path = CACHE_ROOT / "quotes.json"
    if not path.exists():
        return False
    try:
        mtime = datetime.utcfromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    if datetime.utcnow() - mtime > timedelta(seconds=ttl):
        return False
    quote_list = _read_quotes()
    current = sorted({normalize_symbol(item.get("symbol")) for item in quote_list if item.get("symbol")})
    expected = sorted({normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)})
    return bool(expected) and current == expected


def check_market_health(
    session,
    *,
    symbols: list[str],
    min_success_ratio: float,
    fallback_history: bool,
    history_duration: str,
    history_bar_size: str,
    history_use_rth: bool,
) -> dict[str, Any]:
    items = fetch_market_snapshots(
        session,
        symbols=symbols,
        store=False,
        fallback_history=fallback_history,
        history_duration=history_duration,
        history_bar_size=history_bar_size,
        history_use_rth=history_use_rth,
    )
    missing_symbols: list[str] = []
    errors: list[str] = []
    for item in items:
        symbol = item.get("symbol") or ""
        if item.get("error") or not item.get("data"):
            missing_symbols.append(symbol)
            if item.get("error"):
                errors.append(f"{symbol}:{item['error']}")
    total = len(items)
    success = total - len(missing_symbols)
    ratio = success / total if total else 0.0
    status = "ok" if ratio >= min_success_ratio else "blocked"
    return {
        "status": status,
        "total": total,
        "success": success,
        "missing_symbols": missing_symbols,
        "errors": errors,
    }
