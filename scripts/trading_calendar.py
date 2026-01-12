#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_SOURCE = "auto"
DEFAULT_EXCHANGE = "XNYS"
DEFAULT_START_DATE = "1990-01-01"
DEFAULT_REFRESH_DAYS = 7
DEFAULT_OVERRIDE_ENABLED = True
DEFAULT_END_DAYS = 365


def resolve_data_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    default_root = Path("/data/share/stock/data")
    if default_root.exists():
        return default_root
    return Path.cwd() / "data"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text or text.lower() in {"null", "none", "na", "n/a"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def trading_calendar_config_path(data_root: Path) -> Path:
    return data_root / "config" / "trading_calendar.json"


def trading_calendar_dir(data_root: Path) -> Path:
    return data_root / "universe" / "trading_calendar"


def trading_calendar_csv_path(data_root: Path, exchange: str) -> Path:
    code = (exchange or "").strip().upper() or DEFAULT_EXCHANGE
    if code in {"XNYS", "NYSE", "US"}:
        name = "nyse_trading_calendar.csv"
    else:
        name = f"{code.lower()}_trading_calendar.csv"
    return trading_calendar_dir(data_root) / name


def trading_calendar_meta_path(data_root: Path) -> Path:
    return trading_calendar_dir(data_root) / "calendar_meta.json"


def trading_calendar_overrides_path(data_root: Path) -> Path:
    return trading_calendar_dir(data_root) / "trading_calendar_overrides.csv"


def _default_end_date() -> str:
    return (date.today() + timedelta(days=DEFAULT_END_DAYS)).isoformat()


def _coerce_int(value: Any, default: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return num if num >= 0 else default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _defaults() -> dict[str, Any]:
    return {
        "source": DEFAULT_SOURCE,
        "exchange": DEFAULT_EXCHANGE,
        "start_date": DEFAULT_START_DATE,
        "end_date": _default_end_date(),
        "refresh_days": DEFAULT_REFRESH_DAYS,
        "override_enabled": DEFAULT_OVERRIDE_ENABLED,
    }


def load_trading_calendar_config(data_root: Path) -> dict[str, Any]:
    config = _defaults()
    path = trading_calendar_config_path(data_root)
    updated_at = None
    source = "default"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                config["source"] = str(payload.get("source") or config["source"])
                config["exchange"] = str(payload.get("exchange") or config["exchange"])
                config["start_date"] = str(payload.get("start_date") or config["start_date"])
                config["end_date"] = str(payload.get("end_date") or config["end_date"])
                config["refresh_days"] = _coerce_int(
                    payload.get("refresh_days"), config["refresh_days"]
                )
                config["override_enabled"] = _coerce_bool(
                    payload.get("override_enabled"), config["override_enabled"]
                )
                updated_at = payload.get("updated_at")
                source = "file"
        except (OSError, json.JSONDecodeError):
            source = "default"
    config["source"] = (config.get("source") or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE
    config["exchange"] = (config.get("exchange") or DEFAULT_EXCHANGE).strip() or DEFAULT_EXCHANGE
    config["start_date"] = config.get("start_date") or DEFAULT_START_DATE
    config["end_date"] = config.get("end_date") or _default_end_date()
    config["refresh_days"] = _coerce_int(config.get("refresh_days"), DEFAULT_REFRESH_DAYS)
    config["override_enabled"] = _coerce_bool(
        config.get("override_enabled"), DEFAULT_OVERRIDE_ENABLED
    )
    config["updated_at"] = updated_at
    config["config_source"] = source
    config["path"] = str(path)
    return config


def load_trading_calendar_meta(data_root: Path) -> dict[str, Any]:
    path = trading_calendar_meta_path(data_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_calendar_days(path: Path) -> list[date]:
    days: set[date] = set()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = _parse_date(row.get("date"))
            if not parsed:
                continue
            raw_flag = row.get("is_trading_day")
            if raw_flag is not None and str(raw_flag).strip() != "":
                flag_text = str(raw_flag).strip().lower()
                if flag_text in {"0", "false", "no"}:
                    continue
            days.add(parsed)
    return sorted(days)


def _apply_overrides(days: list[date], overrides_path: Path) -> tuple[list[date], int]:
    if not overrides_path.exists():
        return days, 0
    overrides = 0
    day_set = set(days)
    with overrides_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = _parse_date(row.get("date"))
            if not parsed:
                continue
            kind = (row.get("override_type") or "").strip().lower()
            if kind in {"closed", "holiday", "remove", "removed"}:
                if parsed in day_set:
                    day_set.remove(parsed)
                    overrides += 1
            elif kind in {"open", "add", "added"}:
                if parsed not in day_set:
                    day_set.add(parsed)
                    overrides += 1
    return sorted(day_set), overrides


def _resolve_benchmark_path(
    adjusted_dir: Path, benchmark: str, vendor_preference: list[str]
) -> Path:
    candidates = list(adjusted_dir.glob(f"*_{benchmark}_*.csv"))
    if not candidates:
        candidates = list(adjusted_dir.glob(f"*_{benchmark}.csv"))
    if not candidates:
        raise RuntimeError(f"missing benchmark data for {benchmark}")

    def vendor_rank(path: Path) -> int:
        stem = path.stem
        parts = stem.split("_", 2)
        vendor = parts[1] if len(parts) > 1 else ""
        ranks = {v.upper(): i for i, v in enumerate(vendor_preference)}
        return ranks.get(vendor.upper(), len(ranks) + 1)

    return sorted(candidates, key=vendor_rank)[0]


def _load_benchmark_days(
    adjusted_dir: Path, benchmark: str, vendor_preference: list[str]
) -> list[date]:
    path = _resolve_benchmark_path(adjusted_dir, benchmark, vendor_preference)
    days: set[date] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = _parse_date(row.get("date"))
            if parsed:
                days.add(parsed)
    if not days:
        raise RuntimeError("no trading days found in benchmark data")
    return sorted(days)


def load_trading_days(
    data_root: Path,
    adjusted_dir: Path,
    benchmark: str,
    vendor_preference: list[str],
    source_override: str | None = None,
) -> tuple[list[date], dict[str, Any]]:
    config = load_trading_calendar_config(data_root)
    source = (source_override or config.get("source") or DEFAULT_SOURCE).strip().lower()
    exchange = (config.get("exchange") or DEFAULT_EXCHANGE).strip() or DEFAULT_EXCHANGE
    meta = load_trading_calendar_meta(data_root)
    calendar_path = trading_calendar_csv_path(data_root, exchange)
    overrides_path = trading_calendar_overrides_path(data_root)
    calendar_days: list[date] | None = None
    calendar_source = None
    overrides_applied = 0
    spy_days: list[date] | None = None

    def _load_spy_days() -> list[date] | None:
        nonlocal spy_days
        if spy_days is not None:
            return spy_days
        try:
            spy_days = _load_benchmark_days(adjusted_dir, benchmark, vendor_preference)
        except RuntimeError:
            spy_days = None
        return spy_days

    if source in {"auto", "local", "exchange_calendars", "lean"}:
        days = _load_calendar_days(calendar_path)
        if days:
            calendar_days = days
            calendar_source = meta.get("source") or "local"
            if config.get("override_enabled", True):
                calendar_days, overrides_applied = _apply_overrides(calendar_days, overrides_path)
            if source == "auto":
                spy_loaded = _load_spy_days()
                if spy_loaded:
                    merged = sorted(set(calendar_days).union(spy_loaded))
                    if len(merged) != len(calendar_days):
                        calendar_days = merged
                        calendar_source = f"{calendar_source}+spy"
        elif source != "auto":
            raise RuntimeError(f"missing trading calendar file: {calendar_path}")

    if calendar_days is None:
        calendar_days = _load_spy_days() or []
        calendar_source = "spy"

    calendar_start = calendar_days[0].isoformat() if calendar_days else None
    calendar_end = calendar_days[-1].isoformat() if calendar_days else None
    spy_last = spy_days[-1].isoformat() if spy_days else None

    info = {
        "calendar_source": calendar_source or "local",
        "calendar_exchange": exchange,
        "calendar_path": str(calendar_path) if calendar_path else None,
        "calendar_start": calendar_start,
        "calendar_end": calendar_end,
        "calendar_generated_at": meta.get("generated_at"),
        "calendar_sessions": meta.get("sessions"),
        "overrides_path": str(overrides_path),
        "overrides_applied": overrides_applied,
        "spy_last_date": spy_last,
    }
    return calendar_days, info
