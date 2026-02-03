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


def load_exclude_items(
    data_root: Path | None, include_disabled: bool = False
) -> list[dict[str, str]]:
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
