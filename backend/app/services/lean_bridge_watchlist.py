from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import TradeRun
from app.services.lean_bridge_reader import read_positions
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.project_symbols import build_leader_watchlist


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def merge_symbols(primary: Iterable[str], extra: Iterable[str]) -> list[str]:
    merged = {_normalize_symbol(item) for item in list(primary) + list(extra) if _normalize_symbol(item)}
    return sorted(merged)


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    return sorted({_normalize_symbol(item) for item in symbols if _normalize_symbol(item)})


def _collect_unique_symbols(sources: Iterable[Iterable[str]], *, max_symbols: int) -> list[str]:
    limit = int(max_symbols or 0)
    if limit <= 0:
        limit = 1
    seen: set[str] = set()
    ordered: list[str] = []
    for source in sources:
        for item in source:
            symbol = _normalize_symbol(item)
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            ordered.append(symbol)
            if len(ordered) >= limit:
                return ordered
    return ordered


def _extract_symbol_candidates(item) -> list[str]:
    if isinstance(item, str):
        return [item]
    if isinstance(item, dict):
        for key in ("symbol", "Symbol", "ticker", "Ticker"):
            if key in item:
                return [item.get(key)]
    return []


def _load_positions_symbols(bridge_root: Path) -> list[str]:
    payload = read_positions(bridge_root)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    symbols: list[str] = []
    for item in items:
        for candidate in _extract_symbol_candidates(item):
            symbol = _normalize_symbol(candidate)
            if symbol:
                symbols.append(symbol)
    return symbols


def _load_intent_symbols(intent_path: str) -> list[str]:
    if not intent_path:
        return []
    intent_file = Path(intent_path)
    if not intent_file.exists():
        return []
    try:
        payload = json.loads(intent_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    symbols: list[str] = []
    for item in payload:
        for candidate in _extract_symbol_candidates(item):
            symbol = _normalize_symbol(candidate)
            if symbol:
                symbols.append(symbol)
    return symbols


def _load_active_intent_symbols(session) -> list[str]:
    if session is None:
        return []
    runs = (
        session.query(TradeRun)
        .filter(TradeRun.status.in_(["queued", "running"]))
        .order_by(TradeRun.id.asc())
        .all()
    )
    symbols: list[str] = []
    for run in runs:
        params = run.params or {}
        intent_path = params.get("order_intent_path") if isinstance(params, dict) else None
        symbols.extend(_load_intent_symbols(str(intent_path or "")))
    return symbols


def build_watchlist_payload(symbols: Iterable[str], meta: dict | None = None) -> dict:
    items = _normalize_symbols(symbols)
    payload: dict = {"symbols": items}
    if isinstance(meta, dict):
        for key, value in meta.items():
            if key == "symbols":
                continue
            payload[key] = value
    return payload


def resolve_watchlist_path(bridge_root: Path | None = None) -> Path:
    root = bridge_root or resolve_bridge_root()
    return root / "watchlist.json"


def write_watchlist(path: Path, symbols: Iterable[str], meta: dict | None = None) -> dict:
    meta_payload = dict(meta) if isinstance(meta, dict) else {}
    meta_payload.setdefault(
        "updated_at",
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    payload = build_watchlist_payload(symbols, meta_payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def refresh_leader_watchlist(
    session,
    *,
    max_symbols: int = 200,
    bridge_root: Path | None = None,
) -> dict:
    root = bridge_root or resolve_bridge_root()
    symbols = _collect_unique_symbols(
        [
            _load_positions_symbols(root),
            _load_active_intent_symbols(session),
            build_leader_watchlist(session, max_symbols=max_symbols),
        ],
        max_symbols=max_symbols,
    )
    path = resolve_watchlist_path(root)
    target_symbols = _normalize_symbols(symbols)

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict):
            existing_symbols = existing.get("symbols") if isinstance(existing.get("symbols"), list) else []
            if _normalize_symbols(existing_symbols) == target_symbols:
                return existing

    return write_watchlist(path, symbols)
