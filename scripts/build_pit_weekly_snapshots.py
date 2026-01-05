#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


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


def _load_trading_days(
    adjusted_dir: Path, benchmark: str, vendor_preference: list[str]
) -> list[date]:
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

    path = sorted(candidates, key=vendor_rank)[0]
    dates = pd.read_csv(path, usecols=["date"])["date"]
    series = pd.to_datetime(dates, errors="coerce").dropna()
    days = sorted({d.date() for d in series})
    if not days:
        raise RuntimeError("no trading days found in benchmark data")
    return days


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
) -> list[str]:
    result: list[str] = []
    for symbol, (ipo, delist) in life.items():
        if ipo and snapshot_date < ipo:
            continue
        if delist and snapshot_date > delist:
            continue
        if available_symbols is not None and symbol not in available_symbols:
            continue
        result.append(symbol)
    return sorted(result)


def _write_snapshot(
    output_dir: Path, snapshot_date: date, rebalance_date: date, symbols: Iterable[str]
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pit_{snapshot_date.strftime('%Y%m%d')}.csv"
    with filename.open("w", encoding="utf-8", newline="") as handle:
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
    parser.add_argument("--require-data", action="store_true")
    parser.add_argument("--vendor-preference", default="Alpha,Lean,Stooq")
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
    trading_days = _load_trading_days(adjusted_dir, args.benchmark.strip().upper(), vendor_preference)
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
    }
    meta_path = output_dir / "pit_weekly_calendar.json"
    meta_path.write_text(json.dumps(calendar_meta, ensure_ascii=False, indent=2), encoding="utf-8")
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

    index_map = {day: idx for idx, day in enumerate(trading_days)}
    written = 0
    for rebalance_date in rebalance_dates:
        idx = index_map.get(rebalance_date)
        if idx is None or idx == 0:
            continue
        snapshot_date = trading_days[idx - 1]
        symbols = _filter_symbols(life, snapshot_date, available_symbols)
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
