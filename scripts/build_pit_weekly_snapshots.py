#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import trading_calendar


def _resolve_data_root(value: str | None) -> Path:
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
    return datetime.strptime(text, "%Y-%m-%d").date()


def _load_symbol_map(
    path: Path,
) -> dict[str, list[tuple[date | None, date | None, str]]]:
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]] = {}
    if not path.exists():
        return symbol_map
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            canonical = (row.get("canonical") or "").strip().upper()
            if not symbol or not canonical:
                continue
            start = _parse_date(row.get("start_date") or row.get("from_date") or "")
            end = _parse_date(row.get("end_date") or row.get("to_date") or "")
            symbol_map.setdefault(symbol, []).append((start, end, canonical))
    for entries in symbol_map.values():
        entries.sort(key=lambda item: item[0] or date.min)
    return symbol_map


def _resolve_symbol_alias(
    symbol: str,
    as_of: date | None,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
) -> str:
    entries = symbol_map.get(symbol)
    if not entries:
        return symbol
    if as_of:
        match = None
        for start, end, canonical in entries:
            if start and as_of < start:
                continue
            if end and as_of > end:
                continue
            match = canonical
        if match:
            return match
    return entries[-1][2]


def _extract_symbol_from_filename(path: Path) -> str:
    stem = path.stem
    parts = stem.split("_", 2)
    if len(parts) >= 3:
        symbol_part = parts[2]
    else:
        symbol_part = stem
    for suffix in ("_Daily", "_daily", "_D", "_d"):
        if symbol_part.endswith(suffix):
            symbol_part = symbol_part[: -len(suffix)]
            break
    return symbol_part.strip().upper()


def _load_available_symbols(adjusted_dir: Path) -> set[str]:
    symbols = set()
    for path in adjusted_dir.glob("*.csv"):
        parts = path.stem.split("_", 2)
        vendor = parts[1] if len(parts) >= 3 else ""
        if vendor.upper() != "ALPHA":
            continue
        symbol = _extract_symbol_from_filename(path)
        if symbol:
            symbols.add(symbol)
    return symbols


def _load_symbol_life(
    path: Path, asset_type: str | None
) -> dict[str, tuple[date | None, date | None]]:
    life: dict[str, tuple[date | None, date | None]] = {}
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if asset_type:
                raw_type = (row.get("assetType") or "").strip().lower()
                if raw_type and raw_type != asset_type.lower():
                    continue
            ipo = _parse_date(row.get("ipoDate"))
            delist = _parse_date(row.get("delistingDate"))
            life[symbol] = (ipo, delist)
    return life


def _pick_rebalance_dates(
    trading_days: list[date],
    start: date | None,
    end: date | None,
    weekday: int | None,
    mode: str,
) -> list[date]:
    dates: list[date] = []
    if mode == "week_open":
        last_week: tuple[int, int] | None = None
        for day in trading_days:
            if start and day < start:
                continue
            if end and day > end:
                break
            week_key = day.isocalendar()[:2]
            if week_key != last_week:
                dates.append(day)
                last_week = week_key
        return dates

    if weekday is None:
        raise RuntimeError("weekday required for rebalance-mode=weekday")
    for day in trading_days:
        if start and day < start:
            continue
        if end and day > end:
            break
        if day.weekday() == weekday:
            dates.append(day)
    return dates


def _filter_symbols(
    life: dict[str, tuple[date | None, date | None]],
    snapshot_date: date,
    available_symbols: set[str] | None,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
) -> list[str]:
    result: list[str] = []
    for symbol, (ipo, delist) in life.items():
        if ipo and snapshot_date < ipo:
            continue
        if delist and snapshot_date > delist:
            continue
        if available_symbols is not None:
            mapped = _resolve_symbol_alias(symbol, snapshot_date, symbol_map)
            if symbol not in available_symbols and mapped not in available_symbols:
                continue
        result.append(symbol)
    return sorted(result)


def _write_snapshot(
    output_dir: Path, snapshot_date: date, rebalance_date: date, symbols: Iterable[str]
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pit_{snapshot_date.strftime('%Y%m%d')}.csv"
    tmp_path = filename.with_suffix(f"{filename.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "snapshot_date", "rebalance_date"])
        writer.writeheader()
        for symbol in symbols:
            writer.writerow(
                {
                    "symbol": symbol,
                    "snapshot_date": snapshot_date.isoformat(),
                    "rebalance_date": rebalance_date.isoformat(),
                }
            )
    tmp_path.replace(filename)
    return filename


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--symbol-life", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--rebalance-day", default="monday")
    parser.add_argument("--rebalance-mode", default="week_open")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--market-timezone", default="America/New_York")
    parser.add_argument("--session-open", default="09:30")
    parser.add_argument("--session-close", default="16:00")
    parser.add_argument("--asset-type", default="Stock")
    parser.add_argument(
        "--calendar-source",
        default="",
        help="trading calendar source override (auto/local/exchange_calendars/lean/spy)",
    )
    parser.add_argument("--require-data", action="store_true")
    parser.add_argument("--vendor-preference", default="Alpha")
    parser.add_argument("--symbol-map", default="")
    args = parser.parse_args()

    data_root = _resolve_data_root(args.data_root)
    adjusted_dir = data_root / "curated_adjusted"
    if not adjusted_dir.exists():
        raise RuntimeError(f"missing curated_adjusted: {adjusted_dir}")

    symbol_life_path = args.symbol_life.strip()
    if not symbol_life_path:
        symbol_life_path = str(data_root / "universe" / "alpha_symbol_life.csv")
    symbol_life_file = Path(symbol_life_path)
    if not symbol_life_file.is_absolute():
        symbol_life_file = data_root / symbol_life_file
    if not symbol_life_file.exists():
        raise RuntimeError(f"missing symbol life file: {symbol_life_file}")

    output_dir = Path(args.output_dir) if args.output_dir else data_root / "universe" / "pit_weekly"
    if not output_dir.is_absolute():
        output_dir = data_root / output_dir

    weekday_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
    }
    rebalance_mode = (args.rebalance_mode or "").strip().lower()
    if rebalance_mode not in {"week_open", "weekday"}:
        raise RuntimeError("rebalance-mode must be week_open or weekday")
    weekday = None
    if rebalance_mode == "weekday":
        weekday = weekday_map.get(args.rebalance_day.strip().lower())
        if weekday is None:
            raise RuntimeError("rebalance-day must be monday..friday")

    vendor_preference = [item.strip() for item in args.vendor_preference.split(",") if item.strip()]
    vendor_preference = [
        item for item in vendor_preference if item.upper() == "ALPHA"
    ] or ["Alpha"]
    calendar_override = args.calendar_source.strip().lower() or None
    trading_days, calendar_info = trading_calendar.load_trading_days(
        data_root,
        adjusted_dir,
        args.benchmark.strip().upper(),
        vendor_preference,
        source_override=calendar_override,
    )
    start = _parse_date(args.start) if args.start else None
    end = _parse_date(args.end) if args.end else None
    calendar_meta = {
        "calendar_symbol": args.benchmark.strip().upper(),
        "market_timezone": args.market_timezone.strip() or "America/New_York",
        "market_session_open": args.session_open.strip() or "09:30",
        "market_session_close": args.session_close.strip() or "16:00",
        "rebalance_mode": rebalance_mode,
        "rebalance_day": args.rebalance_day.strip().lower(),
        "snapshot_rule": "previous_trading_close",
        "calendar_source": calendar_info.get("calendar_source"),
        "calendar_exchange": calendar_info.get("calendar_exchange"),
        "calendar_start": calendar_info.get("calendar_start"),
        "calendar_end": calendar_info.get("calendar_end"),
        "calendar_generated_at": calendar_info.get("calendar_generated_at"),
        "calendar_sessions": calendar_info.get("calendar_sessions"),
        "calendar_path": calendar_info.get("calendar_path"),
        "overrides_path": calendar_info.get("overrides_path"),
        "overrides_applied": calendar_info.get("overrides_applied"),
        "spy_last_date": calendar_info.get("spy_last_date"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_path = output_dir / "pit_weekly_calendar.json"
    tmp_meta = meta_path.with_suffix(".tmp")
    tmp_meta.write_text(json.dumps(calendar_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_meta.replace(meta_path)
    print(
        "calendar: "
        f"{calendar_meta['calendar_symbol']} "
        f"tz={calendar_meta['market_timezone']} "
        f"session={calendar_meta['market_session_open']}-{calendar_meta['market_session_close']} "
        f"rebalance={calendar_meta['rebalance_mode']}"
    )
    rebalance_dates = _pick_rebalance_dates(
        trading_days, start, end, weekday, rebalance_mode
    )
    if not rebalance_dates:
        raise RuntimeError("no rebalance dates found")

    life = _load_symbol_life(symbol_life_file, args.asset_type.strip() or None)
    available_symbols = _load_available_symbols(adjusted_dir) if args.require_data else None
    symbol_map_path = str(args.symbol_map or "").strip()
    if not symbol_map_path:
        candidate = data_root / "universe" / "symbol_map.csv"
        if candidate.exists():
            symbol_map_path = str(candidate)
    symbol_map = _load_symbol_map(Path(symbol_map_path)) if symbol_map_path else {}

    index_map = {day: idx for idx, day in enumerate(trading_days)}
    written = 0
    for rebalance_date in rebalance_dates:
        idx = index_map.get(rebalance_date)
        if idx is None or idx == 0:
            continue
        snapshot_date = trading_days[idx - 1]
        symbols = _filter_symbols(life, snapshot_date, available_symbols, symbol_map)
        if not symbols:
            continue
        path = _write_snapshot(output_dir, snapshot_date, rebalance_date, symbols)
        written += 1
        print(f"snapshot: {path} symbols={len(symbols)}")

    if not written:
        raise RuntimeError("no snapshots generated")
    print(f"total snapshots: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
