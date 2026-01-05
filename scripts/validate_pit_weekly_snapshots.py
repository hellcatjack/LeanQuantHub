#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime
from pathlib import Path

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
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_snapshot_date(path: Path) -> date | None:
    stem = path.stem
    if not stem.startswith("pit_"):
        return None
    suffix = stem.split("_", 1)[1]
    try:
        return datetime.strptime(suffix, "%Y%m%d").date()
    except ValueError:
    return None


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


def _load_trading_days(adjusted_dir: Path, benchmark: str, vendor_preference: list[str]) -> list[date]:
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


def _next_trading_day(days: list[date], anchor: date) -> date | None:
    for day in days:
        if day > anchor:
            return day
    return None


def _load_symbol_life(
    path: Path, asset_type: str | None
) -> dict[str, tuple[date | None, date | None]]:
    life: dict[str, tuple[date | None, date | None]] = {}
    if not path.exists():
        return life
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


def _write_summary(path: Path | None, payload: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _write_snapshot(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "snapshot_date", "rebalance_date"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--pit-dir", default="")
    parser.add_argument("--symbol-life", default="")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--asset-type", default="Stock")
    parser.add_argument("--vendor-preference", default="Alpha,Lean,Stooq")
    parser.add_argument("--require-data", action="store_true")
    parser.add_argument("--symbol-map", default="")
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--drop-out-of-life", action="store_true")
    parser.add_argument("--drop-no-data", action="store_true")
    parser.add_argument("--summary-path", default="")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    data_root = _resolve_data_root(args.data_root)
    pit_dir = Path(args.pit_dir) if args.pit_dir else data_root / "universe" / "pit_weekly"
    if not pit_dir.is_absolute():
        pit_dir = data_root / pit_dir
    if not pit_dir.exists():
        raise RuntimeError(f"missing pit snapshots: {pit_dir}")

    adjusted_dir = data_root / "curated_adjusted"
    if not adjusted_dir.exists():
        raise RuntimeError(f"missing curated_adjusted: {adjusted_dir}")

    symbol_life_path = args.symbol_life.strip()
    if not symbol_life_path:
        symbol_life_path = str(data_root / "universe" / "alpha_symbol_life.csv")
    symbol_life_file = Path(symbol_life_path)
    if not symbol_life_file.is_absolute():
        symbol_life_file = data_root / symbol_life_file

    vendor_preference = [item.strip() for item in args.vendor_preference.split(",") if item.strip()]
    trading_days = _load_trading_days(adjusted_dir, args.benchmark.strip().upper(), vendor_preference)

    life = _load_symbol_life(symbol_life_file, args.asset_type.strip() or None)
    symbol_map_path = args.symbol_map.strip()
    if not symbol_map_path:
        symbol_map_path = str(data_root / "universe" / "symbol_map.csv")
    symbol_map_file = Path(symbol_map_path)
    if not symbol_map_file.is_absolute():
        symbol_map_file = data_root / symbol_map_file
    symbol_map = _load_symbol_map(symbol_map_file) if symbol_map_file.exists() else {}
    available_symbols = _load_available_symbols(adjusted_dir) if args.require_data else None

    summary = {
        "snapshots": 0,
        "symbols": 0,
        "duplicates": 0,
        "invalid_rows": 0,
        "date_mismatches": 0,
        "out_of_life": 0,
        "no_data": 0,
        "fixed_files": 0,
    }
    strict_issue = False
    for path in sorted(pit_dir.glob("pit_*.csv")):
        snapshot_date = _parse_snapshot_date(path)
        if not snapshot_date:
            print(f"invalid_snapshot_file: {path}")
            strict_issue = True
            continue
        expected_rebalance = _next_trading_day(trading_days, snapshot_date)
        if expected_rebalance is None:
            print(f"missing_rebalance_date: {path}")
            strict_issue = True
            continue

        seen: set[str] = set()
        rows: list[dict[str, str]] = []
        duplicates = 0
        invalid_rows = 0
        date_mismatches = 0
        out_of_life = 0
        no_data = 0
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = (row.get("symbol") or "").strip().upper()
                if not symbol:
                    invalid_rows += 1
                    continue
                if symbol in seen:
                    duplicates += 1
                    if not args.fix:
                        continue
                seen.add(symbol)

                snapshot_raw = row.get("snapshot_date")
                rebalance_raw = row.get("rebalance_date")
                row_snapshot = _parse_date(snapshot_raw)
                row_rebalance = _parse_date(rebalance_raw)
                if row_snapshot != snapshot_date or row_rebalance != expected_rebalance:
                    date_mismatches += 1

                if life:
                    ipo, delist = life.get(symbol, (None, None))
                    if (ipo and snapshot_date < ipo) or (delist and snapshot_date > delist):
                        out_of_life += 1
                        if args.drop_out_of_life:
                            continue

                mapped_symbol = _resolve_symbol_alias(symbol, snapshot_date, symbol_map)
                if available_symbols is not None and mapped_symbol not in available_symbols:
                    no_data += 1
                    if args.drop_no_data or args.require_data:
                        continue

                rows.append(
                    {
                        "symbol": symbol,
                        "snapshot_date": snapshot_date.isoformat()
                        if args.fix or row_snapshot is None
                        else row_snapshot.isoformat(),
                        "rebalance_date": expected_rebalance.isoformat()
                        if args.fix or row_rebalance is None
                        else row_rebalance.isoformat(),
                    }
                )

        rows.sort(key=lambda item: item["symbol"])
        if args.fix and rows:
            _write_snapshot(path, rows)
            summary["fixed_files"] += 1

        summary["snapshots"] += 1
        summary["symbols"] += len(rows)
        summary["duplicates"] += duplicates
        summary["invalid_rows"] += invalid_rows
        summary["date_mismatches"] += date_mismatches
        summary["out_of_life"] += out_of_life
        summary["no_data"] += no_data

        has_issue = any([duplicates, invalid_rows, date_mismatches, out_of_life, no_data])
        if has_issue or args.verbose:
            print(
                "snapshot_check: "
                f"{path.name} symbols={len(rows)} dup={duplicates} invalid={invalid_rows} "
                f"date_mismatch={date_mismatches} out_of_life={out_of_life} no_data={no_data}"
            )

    print(
        "quality_summary: "
        f"snapshots={summary['snapshots']} symbols={summary['symbols']} "
        f"dup={summary['duplicates']} invalid={summary['invalid_rows']} "
        f"date_mismatch={summary['date_mismatches']} out_of_life={summary['out_of_life']} "
        f"no_data={summary['no_data']} fixed_files={summary['fixed_files']}"
    )
    summary["updated_at"] = datetime.utcnow().isoformat()
    _write_summary(Path(args.summary_path).expanduser().resolve() if args.summary_path else None, summary)

    if args.strict and (
        strict_issue
        or summary["duplicates"]
        or summary["invalid_rows"]
        or summary["date_mismatches"]
        or summary["out_of_life"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
