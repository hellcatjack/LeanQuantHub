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


def _select_report(reports: list[dict], cutoff_date: date) -> dict | None:
    selected = None
    for report in reports:
        reported_date = report.get("reported_date") or report.get("fiscal_date")
        if not reported_date or reported_date > cutoff_date:
            continue
        selected_date = (
            (selected.get("reported_date") or selected.get("fiscal_date")) if selected else None
        )
        if not selected or not selected_date or reported_date > selected_date:
            selected = report
    return selected


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
        "lag_days",
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
    with filename.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    return filename


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--pit-dir", default="")
    parser.add_argument("--fundamentals-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--report-delay-days", type=int, default=1)
    parser.add_argument("--min-coverage", type=float, default=0.05)
    parser.add_argument("--coverage-action", default="warn")
    parser.add_argument("--only-with-data", action="store_true")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--vendor-preference", default="Alpha,Lean,Stooq")
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

    adjusted_dir = data_root / "curated_adjusted"
    vendor_preference = [item.strip() for item in args.vendor_preference.split(",") if item.strip()]
    trading_days = _load_trading_days(adjusted_dir, args.benchmark.strip().upper(), vendor_preference)

    snapshots = _load_pit_snapshots(pit_dir, start, end)
    if not snapshots:
        raise RuntimeError("no pit snapshots found")

    cache: dict[str, list[dict]] = {}
    total_symbols = 0
    total_with_data = 0
    written = 0
    for snapshot_date in sorted(snapshots.keys()):
        rebalance_date, symbols = snapshots[snapshot_date]
        total_symbols += len(symbols)
        cutoff_date = _shift_trading_day(trading_days, snapshot_date, -args.report_delay_days)
        rows: list[dict[str, object]] = []
        with_data = 0
        for symbol in symbols:
            if symbol not in cache:
                cache[symbol] = _load_symbol_reports(fundamentals_dir / symbol)
            reports = cache[symbol]
            report = _select_report(reports, cutoff_date)
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
                available_date = report.get("reported_date") or report.get("fiscal_date")
                lag_days = (
                    (snapshot_date - available_date).days if available_date else None
                )
                row.update(
                    {
                        "fiscal_date": report.get("fiscal_date").isoformat()
                        if report.get("fiscal_date")
                        else "",
                        "reported_date": report.get("reported_date").isoformat()
                        if report.get("reported_date")
                        else "",
                        "available_date": available_date.isoformat() if available_date else "",
                        "lag_days": lag_days if lag_days is not None else "",
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
            rows.append(row)
        path = _write_snapshot(output_dir, snapshot_date, rebalance_date, rows)
        ratio = (with_data / len(symbols)) if symbols else 0.0
        written += 1
        print(f"snapshot: {path} symbols={len(rows)} cutoff={cutoff_date.isoformat()}")
        print(
            "coverage: snapshot="
            f"{snapshot_date.strftime('%Y%m%d')} total={len(symbols)} "
            f"with_data={with_data} ratio={ratio:.4f}"
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
    print(f"total snapshots: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
