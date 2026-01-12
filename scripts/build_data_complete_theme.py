#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable


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


def _normalize_symbol(value: str | None) -> str:
    return (value or "").strip().upper()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: Iterable[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        num = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _is_active(row: dict[str, str]) -> bool:
    status = (row.get("status") or "").strip().lower()
    delist = (row.get("delistingDate") or "").strip().lower()
    delist_empty = delist in {"", "null", "none", "nan"}
    if status in {"delisted", "inactive"}:
        return False
    if not delist_empty:
        return False
    return True


def _latest_snapshot_date(pit_dir: Path) -> str | None:
    candidates = sorted(pit_dir.glob("pit_fundamentals_*.csv"))
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stem)
    return latest.stem.replace("pit_fundamentals_", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--pit-fundamentals-dir", default="")
    parser.add_argument("--pit-weekly-dir", default="")
    parser.add_argument("--listing-path", default="")
    parser.add_argument("--output-path", default="")
    parser.add_argument("--meta-path", default="")
    parser.add_argument("--snapshot-date", default="")
    parser.add_argument("--asset-type", default="STOCK")
    parser.add_argument("--vendor-preference", default="Alpha")
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--no-require-fundamentals", dest="require_fundamentals", action="store_false")
    parser.add_argument("--no-require-market-cap", dest="require_market_cap", action="store_false")
    parser.add_argument("--no-require-active", dest="require_active", action="store_false")
    parser.add_argument("--no-require-adjusted", dest="require_adjusted", action="store_false")
    parser.add_argument("--no-require-raw", dest="require_raw", action="store_false")
    parser.set_defaults(
        require_fundamentals=True,
        require_market_cap=True,
        require_active=True,
        require_adjusted=True,
        require_raw=True,
    )
    args = parser.parse_args()

    data_root = _resolve_data_root(args.data_root)
    pit_fund_dir = Path(args.pit_fundamentals_dir) if args.pit_fundamentals_dir else data_root / "factors" / "pit_weekly_fundamentals"
    pit_weekly_dir = Path(args.pit_weekly_dir) if args.pit_weekly_dir else data_root / "universe" / "pit_weekly"
    listing_path = Path(args.listing_path) if args.listing_path else data_root / "universe" / "alpha_symbol_life.csv"

    snapshot_date = args.snapshot_date.strip()
    if not snapshot_date:
        snapshot_date = _latest_snapshot_date(pit_fund_dir) or ""
    if not snapshot_date:
        raise RuntimeError("missing snapshot_date")

    pit_fund_path = pit_fund_dir / f"pit_fundamentals_{snapshot_date}.csv"
    if not pit_fund_path.exists():
        raise RuntimeError(f"missing pit_fundamentals snapshot: {pit_fund_path}")

    pit_weekly_path = pit_weekly_dir / f"pit_{snapshot_date}.csv"
    pit_weekly_symbols = None
    if pit_weekly_path.exists():
        pit_weekly_symbols = {
            _normalize_symbol(row.get("symbol"))
            for row in _read_csv(pit_weekly_path)
            if _normalize_symbol(row.get("symbol"))
        }

    vendor_preference = [
        item.strip().upper()
        for item in str(args.vendor_preference).split(",")
        if item.strip()
    ]
    vendor_preference = [item for item in vendor_preference if item == "ALPHA"] or ["ALPHA"]
    min_rows = max(int(args.min_rows or 0), 0)

    listing_rows = _read_csv(listing_path)
    listing_meta = {}
    asset_type_filter = (args.asset_type or "").strip().upper()
    for row in listing_rows:
        symbol = _normalize_symbol(row.get("symbol"))
        if not symbol:
            continue
        listing_meta[symbol] = {
            "assetType": (row.get("assetType") or "").strip().upper(),
            "active": _is_active(row),
        }

    exclude_symbols = set()
    for name in ("exclude_symbols.csv", "fundamentals_exclude.csv", "fundamentals_missing.csv"):
        path = data_root / "universe" / name
        for row in _read_csv(path):
            sym = _normalize_symbol(row.get("symbol"))
            if sym:
                exclude_symbols.add(sym)

    adjusted_dir = data_root / "curated_adjusted"
    raw_dir = data_root / "curated"

    def _parse_dataset_name(path: Path) -> tuple[str, str]:
        stem = path.stem
        parts = stem.split("_", 1)
        dataset_name = parts[1] if len(parts) == 2 else stem
        tokens = dataset_name.split("_")
        vendor = tokens[0] if tokens else ""
        symbol = tokens[1] if len(tokens) > 1 else ""
        return vendor, symbol

    def _count_rows(path: Path) -> int:
        count = 0
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for _ in handle:
                count += 1
        return max(count - 1, 0)

    def _pick_dataset_file(symbol: str, root: Path) -> Path | None:
        symbol = symbol.upper()
        candidates = list(root.glob(f"*_{symbol}_*.csv"))
        if not candidates:
            candidates = list(root.glob(f"*_{symbol}.csv"))
        if not candidates:
            return None
        vendor_rank = {vendor: idx for idx, vendor in enumerate(vendor_preference)}
        best = None
        best_score = None
        for path in candidates:
            vendor, _ = _parse_dataset_name(path)
            rank = vendor_rank.get(vendor.upper(), len(vendor_rank) + 1)
            rows = _count_rows(path)
            score = (rank, -rows)
            if best_score is None or score < best_score:
                best = path
                best_score = score
        return best

    pit_rows = _read_csv(pit_fund_path)
    eligible = []
    rejected: dict[str, int] = {}
    for row in pit_rows:
        symbol = _normalize_symbol(row.get("symbol"))
        if not symbol:
            continue
        if pit_weekly_symbols is not None and symbol not in pit_weekly_symbols:
            rejected["not_in_weekly"] = rejected.get("not_in_weekly", 0) + 1
            continue
        if symbol in exclude_symbols:
            rejected["excluded_symbols"] = rejected.get("excluded_symbols", 0) + 1
            continue
        listing = listing_meta.get(symbol)
        if args.require_active:
            if not listing or not listing.get("active"):
                rejected["inactive"] = rejected.get("inactive", 0) + 1
                continue
        if asset_type_filter:
            if not listing or listing.get("assetType") != asset_type_filter:
                rejected["asset_type_mismatch"] = rejected.get("asset_type_mismatch", 0) + 1
                continue
        if args.require_fundamentals:
            if str(row.get("has_fundamentals") or "").strip() != "1":
                rejected["missing_fundamentals"] = rejected.get("missing_fundamentals", 0) + 1
                continue
        if args.require_market_cap:
            if _parse_float(row.get("shares_outstanding")) is None:
                rejected["missing_shares"] = rejected.get("missing_shares", 0) + 1
                continue
            if _parse_float(row.get("pit_market_cap")) is None:
                rejected["missing_market_cap"] = rejected.get("missing_market_cap", 0) + 1
                continue
        if args.require_adjusted:
            path = _pick_dataset_file(symbol, adjusted_dir)
            if not path:
                rejected["missing_adjusted_price"] = rejected.get("missing_adjusted_price", 0) + 1
                continue
            if min_rows and _count_rows(path) < min_rows:
                rejected["adjusted_rows_too_few"] = rejected.get("adjusted_rows_too_few", 0) + 1
                continue
        if args.require_raw:
            path = _pick_dataset_file(symbol, raw_dir)
            if not path:
                rejected["missing_raw_price"] = rejected.get("missing_raw_price", 0) + 1
                continue
            if min_rows and _count_rows(path) < min_rows:
                rejected["raw_rows_too_few"] = rejected.get("raw_rows_too_few", 0) + 1
                continue
        eligible.append(symbol)

    eligible = sorted(set(eligible))
    output_path = Path(args.output_path) if args.output_path else data_root / "universe" / "data_complete_symbols.csv"
    meta_path = Path(args.meta_path) if args.meta_path else output_path.with_suffix(".meta.json")

    rows = [{"symbol": symbol} for symbol in eligible]
    _write_csv(output_path, rows, ["symbol"])

    meta = {
        "generated_at": datetime.utcnow().isoformat(),
        "snapshot_date": snapshot_date,
        "pit_fundamentals_path": str(pit_fund_path),
        "pit_weekly_path": str(pit_weekly_path) if pit_weekly_symbols is not None else "",
        "listing_path": str(listing_path),
        "require_fundamentals": bool(args.require_fundamentals),
        "require_market_cap": bool(args.require_market_cap),
        "require_active": bool(args.require_active),
        "require_adjusted": bool(args.require_adjusted),
        "require_raw": bool(args.require_raw),
        "asset_type": asset_type_filter,
        "vendor_preference": vendor_preference,
        "min_rows": min_rows,
        "exclude_symbols_count": len(exclude_symbols),
        "symbol_count": len(eligible),
        "rejected_counts": rejected,
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"output={output_path} count={len(eligible)} snapshot={snapshot_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
