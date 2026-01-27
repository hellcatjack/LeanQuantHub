from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.services.lean_bridge_paths import resolve_bridge_root


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def merge_symbols(primary: Iterable[str], extra: Iterable[str]) -> list[str]:
    merged = {_normalize_symbol(item) for item in list(primary) + list(extra) if _normalize_symbol(item)}
    return sorted(merged)


def build_watchlist_payload(symbols: Iterable[str], meta: dict | None = None) -> dict:
    items = sorted({_normalize_symbol(item) for item in symbols if _normalize_symbol(item)})
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
