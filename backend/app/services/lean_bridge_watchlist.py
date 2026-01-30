from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.project_symbols import build_leader_watchlist


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def merge_symbols(primary: Iterable[str], extra: Iterable[str]) -> list[str]:
    merged = {_normalize_symbol(item) for item in list(primary) + list(extra) if _normalize_symbol(item)}
    return sorted(merged)


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    return sorted({_normalize_symbol(item) for item in symbols if _normalize_symbol(item)})


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
    symbols = build_leader_watchlist(session, max_symbols=max_symbols)
    path = resolve_watchlist_path(bridge_root)
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
