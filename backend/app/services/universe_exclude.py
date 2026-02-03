from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.services.job_lock import JobLock

CSV_HEADER = ["symbol", "enabled", "reason", "source", "created_at", "updated_at"]
DEFAULT_EXCLUDES = ["WY", "XOM", "YUM"]
LEGACY_PATHS = [
    "universe/alpha_exclude_symbols.csv",
    "universe/fundamentals_exclude.csv",
    "universe/fundamentals_missing.csv",
]


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def exclude_symbols_path(data_root: Path | None = None) -> Path:
    root = data_root or _resolve_data_root()
    return root / "universe" / "exclude_symbols.csv"


def ensure_exclude_file(data_root: Path | None = None) -> Path:
    path = exclude_symbols_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    now = datetime.utcnow().isoformat()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for symbol in DEFAULT_EXCLUDES:
            writer.writerow([symbol, "true", "global exclude", "manual/ui", now, now])
    return path


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _read_items_from_path(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    items: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and "symbol" in reader.fieldnames:
                for row in reader:
                    symbol = _normalize_symbol(row.get("symbol") or "")
                    if not symbol:
                        continue
                    row["symbol"] = symbol
                    items.append(dict(row))
                return items
            handle.seek(0)
            for line in handle:
                symbol = _normalize_symbol(line.strip())
                if symbol and symbol != "SYMBOL":
                    items.append({"symbol": symbol})
    except OSError:
        return items
    return items


def merge_legacy_excludes(data_root: Path | None) -> int:
    root = data_root or _resolve_data_root()
    path = ensure_exclude_file(root)
    existing_items = _read_items_from_path(path)
    existing_map = {
        _normalize_symbol(item.get("symbol") or ""): item for item in existing_items
    }
    new_symbols: set[str] = set()
    for rel in LEGACY_PATHS:
        legacy_path = root / rel
        for row in _read_items_from_path(legacy_path):
            symbol = _normalize_symbol(row.get("symbol") or "")
            if symbol and symbol not in existing_map:
                new_symbols.add(symbol)

    if not new_symbols:
        return 0

    now = datetime.utcnow().isoformat()
    for symbol in new_symbols:
        existing_items.append(
            {
                "symbol": symbol,
                "enabled": "true",
                "reason": "legacy",
                "source": "import/legacy",
                "created_at": now,
                "updated_at": now,
            }
        )
    _write_items(root, existing_items)
    return len(new_symbols)


def load_exclude_items(
    data_root: Path | None, include_disabled: bool = False
) -> list[dict[str, str]]:
    merge_legacy_excludes(data_root)
    path = ensure_exclude_file(data_root)
    items: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = _normalize_symbol(row.get("symbol") or "")
            if not symbol:
                continue
            enabled = (row.get("enabled") or "").strip().lower() != "false"
            if not include_disabled and not enabled:
                continue
            row["symbol"] = symbol
            row["enabled"] = "true" if enabled else "false"
            items.append(dict(row))
    return items


def load_exclude_symbols(data_root: Path | None) -> set[str]:
    return {item["symbol"] for item in load_exclude_items(data_root, False)}


def load_exclude_reason_map(data_root: Path | None) -> dict[str, str]:
    items = load_exclude_items(data_root, include_disabled=False)
    return {item["symbol"]: (item.get("reason") or "") for item in items}


def upsert_exclude_item(
    data_root: Path | None,
    *,
    symbol: str,
    reason: str,
    source: str,
    enabled: bool = True,
) -> None:
    cleaned = _normalize_symbol(symbol)
    if not cleaned:
        return
    lock = JobLock("exclude_symbols", data_root)
    if not lock.acquire():
        raise RuntimeError("exclude_symbols_lock_busy")
    try:
        items = load_exclude_items(data_root, include_disabled=True)
        now = datetime.utcnow().isoformat()
        updated = False
        for row in items:
            if row["symbol"] == cleaned:
                row["enabled"] = "true" if enabled else "false"
                row["reason"] = reason
                row["source"] = source
                row["updated_at"] = now
                updated = True
                break
        if not updated:
            items.append(
                {
                    "symbol": cleaned,
                    "enabled": "true" if enabled else "false",
                    "reason": reason,
                    "source": source,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        _write_items(data_root, items)
    finally:
        lock.release()


def set_exclude_enabled(data_root: Path | None, *, symbol: str, enabled: bool) -> None:
    upsert_exclude_item(
        data_root, symbol=symbol, reason="", source="manual/ui", enabled=enabled
    )


def _write_items(data_root: Path | None, items: Iterable[dict[str, str]]) -> None:
    path = ensure_exclude_file(data_root)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for row in items:
            writer.writerow(
                [
                    row.get("symbol", ""),
                    row.get("enabled", "true"),
                    row.get("reason", ""),
                    row.get("source", ""),
                    row.get("created_at", ""),
                    row.get("updated_at", ""),
                ]
            )
