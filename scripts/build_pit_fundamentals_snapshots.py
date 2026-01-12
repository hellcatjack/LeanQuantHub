#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import trading_calendar


REPORT_FIELDS = {
    "income_statement": {
        "totalRevenue": "total_revenue",
        "grossProfit": "gross_profit",
        "operatingIncome": "operating_income",
        "netIncome": "net_income",
    },
    "balance_sheet": {
        "totalAssets": "total_assets",
        "totalLiabilities": "total_liabilities",
        "totalShareholderEquity": "total_shareholder_equity",
        "cashAndCashEquivalentsAtCarryingValue": "cash_and_cash_equivalents",
    },
    "cash_flow": {
        "operatingCashflow": "operating_cashflow",
        "capitalExpenditures": "capital_expenditures",
        "cashflowFromInvestment": "cashflow_from_investment",
        "cashflowFromFinancing": "cashflow_from_financing",
    },
    "earnings": {
        "reportedEPS": "reported_eps",
    },
}


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
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_vendor(path: Path) -> str:
    stem = path.stem
    parts = stem.split("_", 1)
    dataset_name = parts[1] if len(parts) == 2 else stem
    tokens = dataset_name.split("_")
    return tokens[0] if tokens else ""


def _pick_price_file(
    source_dir: Path, symbol: str, vendor_preference: list[str]
) -> Path | None:
    symbol = symbol.upper()
    candidates = list(source_dir.glob(f"*_{symbol}_*.csv"))
    if not candidates:
        candidates = list(source_dir.glob(f"*_{symbol}.csv"))
    if not candidates:
        return None
    vendor_rank = {vendor.upper(): idx for idx, vendor in enumerate(vendor_preference)}
    best = None
    best_rank = None
    for path in candidates:
        vendor = _parse_vendor(path).upper()
        rank = vendor_rank.get(vendor, len(vendor_rank) + 1)
        if best_rank is None or rank < best_rank:
            best = path
            best_rank = rank
    return best


def _load_price_series(path: Path) -> dict[date, float]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, usecols=["date", "close"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date", "close"])
    series: dict[date, float] = {}
    for _, row in df.iterrows():
        try:
            close_val = float(row["close"])
        except (TypeError, ValueError):
            continue
        series[row["date"]] = close_val
    return series


def _load_shares_outstanding(
    symbol_dir: Path, preference: str, shares_delay_days: int
) -> list[tuple[date, float]]:
    path = symbol_dir / "shares_outstanding.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    preference = preference.lower()
    preferred_key = "shares_outstanding_diluted" if preference == "diluted" else "shares_outstanding_basic"
    fallback_key = "shares_outstanding_basic" if preferred_key.endswith("diluted") else "shares_outstanding_diluted"
    result: list[tuple[date, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        report_date = _parse_date(item.get("date"))
        if not report_date:
            continue
        value = _parse_float(item.get(preferred_key))
        if value is None:
            value = _parse_float(item.get(fallback_key))
        if value is None:
            continue
        available_date = report_date + timedelta(days=shares_delay_days) if shares_delay_days else report_date
        result.append((available_date, value))
    result.sort(key=lambda item: item[0])
    return result


def _select_shares(
    shares: list[tuple[date, float]], cutoff_date: date
) -> tuple[float | None, date | None]:
    selected = None
    selected_date = None
    for available_date, value in shares:
        if available_date > cutoff_date:
            break
        selected = value
        selected_date = available_date
    return selected, selected_date


def _resolve_price_close(
    series: dict[date, float],
    trading_days: list[date],
    trading_index: dict[date, int],
    snapshot_date: date,
) -> tuple[float | None, date | None]:
    if not series:
        return None, None
    if snapshot_date in trading_index:
        idx = trading_index[snapshot_date]
    else:
        candidates = [i for i, day in enumerate(trading_days) if day <= snapshot_date]
        idx = max(candidates) if candidates else 0
    for step in range(idx, -1, -1):
        day = trading_days[step]
        if day in series:
            return series[day], day
    return None, None


def _shift_trading_day(days: list[date], anchor: date, offset: int) -> date:
    index_map = {day: idx for idx, day in enumerate(days)}
    if anchor not in index_map:
        candidates = [i for i, day in enumerate(days) if day <= anchor]
        anchor_idx = max(candidates) if candidates else 0
    else:
        anchor_idx = index_map[anchor]
    target_idx = max(min(anchor_idx + offset, len(days) - 1), 0)
    return days[target_idx]


def _load_pit_snapshots(
    pit_dir: Path, start: date | None, end: date | None
) -> dict[date, tuple[date, list[str]]]:
    snapshots: dict[date, tuple[date, list[str]]] = {}
    for path in pit_dir.glob("pit_*.csv"):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = (row.get("symbol") or "").strip().upper()
                snapshot_raw = (row.get("snapshot_date") or "").strip()
                rebalance_raw = (row.get("rebalance_date") or "").strip()
                snapshot_date = _parse_date(snapshot_raw)
                rebalance_date = _parse_date(rebalance_raw)
                if not symbol or not snapshot_date or not rebalance_date:
                    continue
                if start and snapshot_date < start:
                    continue
                if end and snapshot_date > end:
                    continue
                entry = snapshots.setdefault(snapshot_date, (rebalance_date, []))
                entry[1].append(symbol)
    for key in list(snapshots.keys()):
        rebalance_date, symbols = snapshots[key]
        snapshots[key] = (rebalance_date, sorted(set(symbols)))
    return snapshots


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def _merge_reports(base: dict[date, dict], reports: Iterable[dict], fields: dict[str, str]) -> None:
    for report in reports:
        fiscal_raw = report.get("fiscalDateEnding") or report.get("fiscal_date")
        fiscal_date = _parse_date(fiscal_raw)
        if not fiscal_date:
            continue
        reported_date = _parse_date(report.get("reportedDate"))
        entry = base.setdefault(fiscal_date, {"fiscal_date": fiscal_date})
        if reported_date:
            existing = entry.get("reported_date")
            if not existing or reported_date > existing:
                entry["reported_date"] = reported_date
        for source_key, output_key in fields.items():
            value = _parse_float(report.get(source_key))
            if value is None:
                continue
            entry[output_key] = value


def _load_symbol_reports(symbol_dir: Path) -> list[dict]:
    reports: dict[date, dict] = {}
    income = _load_json(symbol_dir / "income_statement.json")
    _merge_reports(reports, income.get("quarterlyReports", []), REPORT_FIELDS["income_statement"])
    balance = _load_json(symbol_dir / "balance_sheet.json")
    _merge_reports(reports, balance.get("quarterlyReports", []), REPORT_FIELDS["balance_sheet"])
    cash = _load_json(symbol_dir / "cash_flow.json")
    _merge_reports(reports, cash.get("quarterlyReports", []), REPORT_FIELDS["cash_flow"])
    earnings = _load_json(symbol_dir / "earnings.json")
    _merge_reports(
        reports,
        earnings.get("quarterlyEarnings", []),
        REPORT_FIELDS["earnings"],
    )
    return [reports[key] for key in sorted(reports.keys())]


def _resolve_available_date(
    report: dict, missing_report_delay_days: int
) -> tuple[date | None, str]:
    reported_date = report.get("reported_date")
    fiscal_date = report.get("fiscal_date")
    if reported_date:
        return reported_date, "reported"
    if fiscal_date and missing_report_delay_days > 0:
        return fiscal_date + timedelta(days=missing_report_delay_days), "default_delay"
    if fiscal_date:
        return fiscal_date, "fiscal_date"
    return None, ""


def _select_report(
    reports: list[dict], cutoff_date: date, missing_report_delay_days: int
) -> tuple[dict | None, date | None, str]:
    selected = None
    selected_available: date | None = None
    selected_source = ""
    for report in reports:
        available_date, source = _resolve_available_date(report, missing_report_delay_days)
        if not available_date or available_date > cutoff_date:
            continue
        if not selected_available or available_date > selected_available:
            selected = report
            selected_available = available_date
            selected_source = source
    return selected, selected_available, selected_source


def _write_snapshot(
    output_dir: Path,
    snapshot_date: date,
    rebalance_date: date,
    rows: list[dict[str, object]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pit_fundamentals_{snapshot_date.strftime('%Y%m%d')}.csv"
    fields = [
        "symbol",
        "has_fundamentals",
        "snapshot_date",
        "rebalance_date",
        "fiscal_date",
        "reported_date",
        "available_date",
        "availability_source",
        "lag_days",
        "filled_forward",
        "shares_outstanding",
        "shares_available_date",
        "shares_source",
        "pit_market_cap",
        "total_revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps",
        "reported_eps",
        "total_assets",
        "total_liabilities",
        "total_shareholder_equity",
        "cash_and_cash_equivalents",
        "operating_cashflow",
        "capital_expenditures",
        "cashflow_from_investment",
        "cashflow_from_financing",
        "free_cashflow",
    ]
    tmp_path = filename.with_suffix(f"{filename.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    tmp_path.replace(filename)
    return filename


def _load_asset_types(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    asset_types: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            asset_type = (row.get("assetType") or "").strip().upper()
            if asset_type:
                asset_types[symbol] = asset_type
    return asset_types


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--pit-dir", default="")
    parser.add_argument("--fundamentals-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--listing-path", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--report-delay-days", type=int, default=1)
    parser.add_argument("--missing-report-delay-days", type=int, default=45)
    parser.add_argument("--shares-delay-days", type=int, default=45)
    parser.add_argument("--shares-preference", default="diluted")
    parser.add_argument("--price-source", default="raw")
    parser.add_argument("--min-coverage", type=float, default=0.05)
    parser.add_argument("--coverage-action", default="warn")
    parser.add_argument("--only-with-data", action="store_true")
    parser.add_argument("--exclude-symbols", default="")
    parser.add_argument("--asset-types", default="STOCK")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument(
        "--calendar-source",
        default="",
        help="trading calendar source override (auto/local/exchange_calendars/lean/spy)",
    )
    parser.add_argument("--vendor-preference", default="Alpha")
    args = parser.parse_args()

    data_root = _resolve_data_root(args.data_root)
    pit_dir = Path(args.pit_dir) if args.pit_dir else data_root / "universe" / "pit_weekly"
    if not pit_dir.is_absolute():
        pit_dir = data_root / pit_dir
    fundamentals_dir = (
        Path(args.fundamentals_dir) if args.fundamentals_dir else data_root / "fundamentals" / "alpha"
    )
    if not fundamentals_dir.is_absolute():
        fundamentals_dir = data_root / fundamentals_dir
    output_dir = Path(args.output_dir) if args.output_dir else data_root / "factors" / "pit_weekly_fundamentals"
    if not output_dir.is_absolute():
        output_dir = data_root / output_dir

    start = _parse_date(args.start) if args.start else None
    end = _parse_date(args.end) if args.end else None
    missing_report_delay_days = max(int(args.missing_report_delay_days or 0), 0)

    listing_path = (
        Path(args.listing_path)
        if args.listing_path
        else data_root / "universe" / "alpha_symbol_life.csv"
    )
    if not listing_path.is_absolute():
        listing_path = data_root / listing_path
    asset_types_raw = [item.strip().upper() for item in args.asset_types.split(",") if item.strip()]
    if "ALL" in asset_types_raw:
        asset_types_raw = []
    asset_type_filter = set(asset_types_raw)
    asset_type_map = _load_asset_types(listing_path) if asset_type_filter else {}
    apply_asset_filter = bool(asset_type_filter) and bool(asset_type_map)
    if asset_type_filter and not asset_type_map:
        print("warning: asset_type filter disabled because listing file is missing/empty")

    adjusted_dir = data_root / "curated_adjusted"
    vendor_preference = [item.strip() for item in args.vendor_preference.split(",") if item.strip()]
    vendor_preference = [
        item for item in vendor_preference if item.upper() == "ALPHA"
    ] or ["Alpha"]
    calendar_override = args.calendar_source.strip().lower() or None
    trading_days, _calendar_info = trading_calendar.load_trading_days(
        data_root,
        adjusted_dir,
        args.benchmark.strip().upper(),
        vendor_preference,
        source_override=calendar_override,
    )
    trading_index = {day: idx for idx, day in enumerate(trading_days)}

    shares_delay_days = max(int(args.shares_delay_days or 0), 0)
    shares_preference = str(args.shares_preference or "diluted").strip().lower()
    if shares_preference not in {"basic", "diluted"}:
        raise RuntimeError("shares_preference must be basic or diluted")
    price_source = str(args.price_source or "raw").strip().lower()
    if price_source not in {"raw", "adjusted"}:
        raise RuntimeError("price_source must be raw or adjusted")
    price_dir = data_root / ("curated" if price_source == "raw" else "curated_adjusted")
    if not price_dir.exists():
        raise RuntimeError(f"missing price_dir: {price_dir}")

    snapshots = _load_pit_snapshots(pit_dir, start, end)
    if not snapshots:
        raise RuntimeError("no pit snapshots found")
    exclude_symbols: set[str] = set()
    exclude_path = str(args.exclude_symbols or "").strip()
    if exclude_path:
        exclude_file = Path(exclude_path)
        if not exclude_file.is_absolute():
            exclude_file = data_root / exclude_file
        if exclude_file.exists():
            for raw in exclude_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                symbol = raw.strip().upper()
                if symbol and symbol != "SYMBOL":
                    exclude_symbols.add(symbol)

    cache: dict[str, list[dict]] = {}
    price_cache: dict[str, dict[date, float]] = {}
    shares_cache: dict[str, list[tuple[date, float]]] = {}
    total_symbols = 0
    total_with_data = 0
    total_excluded_asset_type = 0
    written = 0
    for snapshot_date in sorted(snapshots.keys()):
        rebalance_date, symbols = snapshots[snapshot_date]
        total_symbols += len(symbols)
        cutoff_date = _shift_trading_day(trading_days, snapshot_date, -args.report_delay_days)
        rows: list[dict[str, object]] = []
        with_data = 0
        excluded_asset_type = 0
        for symbol in symbols:
            if exclude_symbols and symbol in exclude_symbols:
                continue
            if apply_asset_filter:
                asset_type = asset_type_map.get(symbol)
                if not asset_type or asset_type not in asset_type_filter:
                    excluded_asset_type += 1
                    continue
            if symbol not in cache:
                cache[symbol] = _load_symbol_reports(fundamentals_dir / symbol)
            reports = cache[symbol]
            report, available_date, availability_source = _select_report(
                reports, cutoff_date, missing_report_delay_days
            )
            has_fundamentals = bool(report)
            if has_fundamentals:
                with_data += 1
                total_with_data += 1
            if args.only_with_data and not has_fundamentals:
                continue
            row: dict[str, object] = {
                "symbol": symbol,
                "has_fundamentals": 1 if has_fundamentals else 0,
                "snapshot_date": snapshot_date.isoformat(),
                "rebalance_date": rebalance_date.isoformat(),
            }
            if report:
                lag_days = (snapshot_date - available_date).days if available_date else None
                filled_forward = bool(available_date and available_date < snapshot_date)
                row.update(
                    {
                        "fiscal_date": report.get("fiscal_date").isoformat()
                        if report.get("fiscal_date")
                        else "",
                        "reported_date": report.get("reported_date").isoformat()
                        if report.get("reported_date")
                        else "",
                        "available_date": available_date.isoformat() if available_date else "",
                        "availability_source": availability_source,
                        "lag_days": lag_days if lag_days is not None else "",
                        "filled_forward": 1 if filled_forward else 0,
                    }
                )
                for key, value in report.items():
                    if key in {"fiscal_date", "reported_date"}:
                        continue
                    row[key] = value
                if row.get("eps") in (None, "") and row.get("reported_eps") not in (None, ""):
                    row["eps"] = row.get("reported_eps")
                op_cf = report.get("operating_cashflow")
                capex = report.get("capital_expenditures")
                if op_cf is not None and capex is not None:
                    row["free_cashflow"] = op_cf - capex
            if symbol not in shares_cache:
                shares_cache[symbol] = _load_shares_outstanding(
                    fundamentals_dir / symbol, shares_preference, shares_delay_days
                )
            shares_series = shares_cache[symbol]
            shares_value, shares_available = _select_shares(shares_series, cutoff_date)
            if shares_value is not None:
                row["shares_outstanding"] = shares_value
                row["shares_available_date"] = (
                    shares_available.isoformat() if shares_available else ""
                )
                row["shares_source"] = f"shares_outstanding_{shares_preference}"
                if symbol not in price_cache:
                    price_path = _pick_price_file(price_dir, symbol, vendor_preference)
                    price_cache[symbol] = _load_price_series(price_path) if price_path else {}
                close_val, _ = _resolve_price_close(
                    price_cache[symbol], trading_days, trading_index, snapshot_date
                )
                if close_val is not None:
                    row["pit_market_cap"] = close_val * shares_value
            rows.append(row)
        path = _write_snapshot(output_dir, snapshot_date, rebalance_date, rows)
        ratio = (with_data / len(symbols)) if symbols else 0.0
        total_excluded_asset_type += excluded_asset_type
        written += 1
        print(f"snapshot: {path} symbols={len(rows)} cutoff={cutoff_date.isoformat()}")
        print(
            "coverage: snapshot="
            f"{snapshot_date.strftime('%Y%m%d')} total={len(symbols)} "
            f"with_data={with_data} ratio={ratio:.4f}"
        )
        if apply_asset_filter:
            print(
                f"asset_filter: snapshot={snapshot_date.strftime('%Y%m%d')} "
                f"excluded={excluded_asset_type}"
            )

    if not written:
        raise RuntimeError("no snapshots generated")
    total_ratio = (total_with_data / total_symbols) if total_symbols else 0.0
    print(
        f"coverage_total: total={total_symbols} with_data={total_with_data} ratio={total_ratio:.4f}"
    )
    if total_with_data == 0:
        raise RuntimeError("no_fundamentals_found")
    min_coverage = max(min(float(args.min_coverage), 1.0), 0.0)
    action = (args.coverage_action or "warn").strip().lower()
    if total_ratio < min_coverage:
        message = f"coverage_below_threshold ratio={total_ratio:.4f} min={min_coverage:.4f}"
        if action == "fail":
            raise RuntimeError(message)
        if action == "warn":
            print(f"coverage_warning: {message}")
        else:
            raise RuntimeError("coverage_action must be warn or fail")
    meta_path = output_dir / "pit_fundamentals_meta.json"
    meta_payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "report_delay_days": int(args.report_delay_days),
        "missing_report_delay_days": missing_report_delay_days,
        "shares_delay_days": shares_delay_days,
        "shares_preference": shares_preference,
        "price_source": price_source,
        "asset_types": sorted(asset_type_filter),
        "asset_types_applied": apply_asset_filter,
        "asset_types_excluded": total_excluded_asset_type,
        "listing_path": str(listing_path),
        "symbol_life_override_path": str(data_root / "universe" / "symbol_life_override.csv"),
        "pit_rule": "week_open_rebalance; snapshot=previous_trading_close",
        "availability_time_et": "06:00",
        "fill_forward": True,
    }
    tmp_meta = meta_path.with_suffix(".tmp")
    tmp_meta.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_meta.replace(meta_path)
    print(f"total snapshots: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
