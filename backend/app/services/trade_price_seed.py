from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_quotes


def _pick_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    for key in ("last", "close", "bid", "ask"):
        value = snapshot.get(key)
        if value is None:
            continue
        try:
            picked = float(value)
        except (TypeError, ValueError):
            continue
        if picked > 0:
            return picked
    return None


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _normalize_symbol_for_filename(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", str(symbol or "").strip().upper())
    return cleaned.strip("_")


def _find_latest_price_file(root: Path, symbol: str) -> Path | None:
    if not root.exists():
        return None
    normalized = _normalize_symbol_for_filename(symbol)
    if not normalized:
        return None
    matches = sorted(root.glob(f"*_{normalized}_Daily.csv"))
    if not matches:
        return None
    return matches[-1]


def _read_latest_close(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            last_row: dict[str, Any] | None = None
            for row in reader:
                last_row = row
        if not last_row:
            return None
        close_value = last_row.get("close")
        if close_value in (None, ""):
            return None
        picked = float(close_value)
        if picked <= 0:
            return None
        return picked
    except (OSError, TypeError, ValueError):
        return None


def _load_fallback_prices(symbols: list[str]) -> dict[str, float]:
    root = _resolve_data_root() / "curated_adjusted"
    prices: dict[str, float] = {}
    for symbol in symbols:
        path = _find_latest_price_file(root, symbol)
        if not path:
            continue
        picked = _read_latest_close(path)
        if picked is not None and picked > 0:
            prices[symbol] = picked
    return prices


def build_price_seed_map(symbols: list[str]) -> dict[str, float]:
    symbol_set = {str(symbol or "").strip().upper() for symbol in symbols if symbol}
    if not symbol_set:
        return {}

    quotes = read_quotes(resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes, dict) and isinstance(quotes.get("items"), list) else []
    prices: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol not in symbol_set:
            continue
        payload = item.get("data") if isinstance(item.get("data"), dict) else item
        picked = _pick_price(payload if isinstance(payload, dict) else None)
        if picked is not None and picked > 0:
            prices[symbol] = picked

    missing = sorted(symbol_set - set(prices.keys()))
    if missing:
        prices.update(_load_fallback_prices(missing))
    return prices


def resolve_price_seed(symbol: str) -> float | None:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return None
    return build_price_seed_map([normalized]).get(normalized)
