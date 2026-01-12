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
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_symbol_from_filename(path: Path) -> str:
    stem = path.stem
    parts = stem.split("_", 2)
    symbol_part = parts[2] if len(parts) >= 3 else stem
    for suffix in ("_Daily", "_daily", "_D", "_d"):
        if symbol_part.endswith(suffix):
            symbol_part = symbol_part[: -len(suffix)]
            break
    return symbol_part.strip().upper()


def _load_symbol_life(path: Path) -> dict[str, tuple[date | None, date | None]]:
    life: dict[str, tuple[date | None, date | None]] = {}
    if not path.exists():
        return life
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            ipo = _parse_date(row.get("ipoDate"))
            delist = _parse_date(row.get("delistingDate"))
            life[symbol] = (ipo, delist)
    return life


def _sanitize_cliffs(
    rows: list[dict[str, str]],
    date_key: str,
    price_columns: list[str],
    threshold: float,
) -> int:
    if not rows:
        return 0
    scale = 1.0
    prev_close: float | None = None
    count = 0
    for row in rows:
        close_val = _parse_float(row.get("close")) if "close" in price_columns else None
        if close_val is None and "adj_close" in price_columns:
            close_val = _parse_float(row.get("adj_close"))
        if close_val is None:
            continue
        scaled_close = close_val * scale
        if prev_close is not None and prev_close > 0:
            pct = (scaled_close - prev_close) / prev_close
            if abs(pct) >= threshold and scaled_close != 0:
                scale *= prev_close / scaled_close
                scaled_close = close_val * scale
                count += 1
        for key in price_columns:
            val = _parse_float(row.get(key))
            if val is None:
                continue
            row[key] = _format_price(val * scale)
        prev_close = scaled_close
    return count


def _write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _build_expected_days(
    trading_days: list[date],
    start: date,
    end: date,
    life: tuple[date | None, date | None] | None,
) -> list[date]:
    ipo, delist = life or (None, None)
    if ipo and start < ipo:
        start = ipo
    if delist and end > delist:
        end = delist
    if start > end:
        return []
    return [day for day in trading_days if start <= day <= end]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--source-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--issues", default="")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument(
        "--calendar-source",
        default="",
        help="trading calendar source override (auto/local/exchange_calendars/lean/spy)",
    )
    parser.add_argument("--vendor-preference", default="Alpha")
    parser.add_argument("--symbol-life", default="")
    parser.add_argument("--outlier-threshold", type=float, default=0.2)
    parser.add_argument("--cliff-threshold", type=float, default=0.6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--fix-output-dir", default="")
    parser.add_argument("--fill-missing", action="store_true")
    parser.add_argument("--drop-duplicates", action="store_true")
    parser.add_argument("--sanitize-cliffs", action="store_true")
    args = parser.parse_args()

    data_root = _resolve_data_root(args.data_root)
    source_dir = Path(args.source_dir) if args.source_dir else data_root / "curated_adjusted"
    if not source_dir.is_absolute():
        source_dir = data_root / source_dir
    if not source_dir.exists():
        raise RuntimeError(f"missing source dir: {source_dir}")

    output_dir = Path(args.output_dir) if args.output_dir else data_root / "metrics" / "price_quality"
    if not output_dir.is_absolute():
        output_dir = data_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary) if args.summary else output_dir / "price_quality_summary.csv"
    if not summary_path.is_absolute():
        summary_path = data_root / summary_path
    issues_path = Path(args.issues) if args.issues else output_dir / "price_quality_issues.csv"
    if not issues_path.is_absolute():
        issues_path = data_root / issues_path

    fix_output_dir = None
    if args.fix:
        fix_output_dir = (
            Path(args.fix_output_dir)
            if args.fix_output_dir
            else data_root / "curated_adjusted_fixed"
        )
        if not fix_output_dir.is_absolute():
            fix_output_dir = data_root / fix_output_dir
        fix_output_dir.mkdir(parents=True, exist_ok=True)

    vendor_preference = [item.strip() for item in args.vendor_preference.split(",") if item.strip()]
    vendor_preference = [
        item for item in vendor_preference if item.upper() == "ALPHA"
    ] or ["Alpha"]
    vendor_allowed = {item.upper() for item in vendor_preference}
    calendar_override = args.calendar_source.strip().lower() or None
    trading_days, _calendar_info = trading_calendar.load_trading_days(
        data_root,
        source_dir,
        args.benchmark.strip().upper(),
        vendor_preference,
        source_override=calendar_override,
    )
    symbol_life_path = args.symbol_life.strip()
    if not symbol_life_path:
        symbol_life_path = str(data_root / "universe" / "alpha_symbol_life.csv")
    symbol_life_file = Path(symbol_life_path)
    if not symbol_life_file.is_absolute():
        symbol_life_file = data_root / symbol_life_file
    symbol_life = _load_symbol_life(symbol_life_file)

    all_files = []
    for path in sorted(source_dir.glob("*.csv")):
        parts = path.stem.split("_", 2)
        vendor = parts[1] if len(parts) >= 3 else ""
        if vendor_allowed and vendor.upper() not in vendor_allowed:
            continue
        all_files.append(path)
    offset = max(args.offset, 0)
    limit = max(args.limit, 0)
    files = all_files[offset:]
    if limit:
        files = files[:limit]

    summaries: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    total_rows = 0
    total_missing = 0
    total_duplicates = 0
    total_outliers = 0
    total_cliffs = 0
    total_fixed = 0

    for path in files:
        rows: list[dict[str, str]] = []
        invalid_dates = 0
        symbol = ""
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                continue
            for row in reader:
                if not symbol:
                    symbol = (row.get("symbol") or "").strip().upper()
                raw_date = row.get("date")
                parsed = _parse_date(raw_date)
                if not parsed:
                    invalid_dates += 1
                    continue
                row["_date"] = parsed.isoformat()
                rows.append(row)
        if not symbol:
            symbol = _extract_symbol_from_filename(path)

        if not rows:
            continue

        rows.sort(key=lambda item: item["_date"])
        unique_rows: dict[str, dict[str, str]] = {}
        duplicates = 0
        for row in rows:
            key = row["_date"]
            if key in unique_rows:
                duplicates += 1
            unique_rows[key] = row
        rows = [unique_rows[key] for key in sorted(unique_rows.keys())]

        header_keys = [key for key in rows[0].keys() if key != "_date"]
        price_columns = [key for key in ("open", "high", "low", "close", "adj_close") if key in header_keys]
        close_key = "close" if "close" in header_keys else ("adj_close" if "adj_close" in header_keys else "")

        dates = [datetime.strptime(row["_date"], "%Y-%m-%d").date() for row in rows]
        start = dates[0]
        end = dates[-1]
        expected_days = _build_expected_days(
            trading_days, start, end, symbol_life.get(symbol)
        )
        expected_count = len(expected_days)
        present_dates = set(dates)
        missing_days = max(expected_count - len(present_dates), 0)
        missing_ratio = (missing_days / expected_count) if expected_count else 0.0

        outliers = 0
        cliffs = 0
        max_abs_return = 0.0
        last_close: float | None = None
        for row in rows:
            close_val = _parse_float(row.get(close_key)) if close_key else None
            if close_val is None:
                continue
            if last_close is not None and last_close != 0:
                ret = (close_val - last_close) / last_close
                max_abs_return = max(max_abs_return, abs(ret))
                if abs(ret) >= args.outlier_threshold:
                    outliers += 1
                if abs(ret) >= args.cliff_threshold:
                    cliffs += 1
            last_close = close_val

        total_rows += len(rows)
        total_missing += missing_days
        total_duplicates += duplicates
        total_outliers += outliers
        total_cliffs += cliffs

        filled_days = 0
        sanitized_cliffs = 0
        if args.fix and fix_output_dir:
            filled_rows: list[dict[str, str]] = []
            expected_set = set(expected_days)
            row_map = {datetime.strptime(row["_date"], "%Y-%m-%d").date(): row for row in rows}
            last_row: dict[str, str] | None = None
            last_close_str = ""
            if expected_days:
                for day in expected_days:
                    row = row_map.get(day)
                    if row:
                        filled_rows.append(row)
                        last_row = row
                        last_close_str = row.get(close_key, "") if close_key else ""
                        continue
                    if not args.fill_missing or not last_row or not last_close_str:
                        continue
                    new_row = {key: last_row.get(key, "") for key in header_keys}
                    new_row["date"] = day.isoformat()
                    new_row["symbol"] = symbol
                    for key in price_columns:
                        new_row[key] = last_close_str
                    if "volume" in new_row:
                        new_row["volume"] = "0"
                    filled_rows.append(new_row)
                    filled_days += 1
            else:
                filled_rows = rows

            if args.sanitize_cliffs:
                sanitized_cliffs = _sanitize_cliffs(
                    filled_rows,
                    "date",
                    price_columns,
                    args.cliff_threshold,
                )

            if args.drop_duplicates:
                deduped: dict[str, dict[str, str]] = {}
                for row in filled_rows:
                    deduped[row.get("date", "")] = row
                filled_rows = [deduped[key] for key in sorted(deduped.keys()) if key]

            output_path = fix_output_dir / path.name
            _write_csv(output_path, filled_rows, header_keys)
            total_fixed += 1

        summary_row = {
            "symbol": symbol,
            "file": str(path),
            "rows": len(rows),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "expected_days": expected_count,
            "missing_days": missing_days,
            "missing_ratio": f"{missing_ratio:.4f}",
            "duplicates": duplicates,
            "invalid_dates": invalid_dates,
            "outlier_returns": outliers,
            "cliff_returns": cliffs,
            "max_abs_return": f"{max_abs_return:.4f}",
            "filled_days": filled_days,
            "sanitized_cliffs": sanitized_cliffs,
        }
        summaries.append(summary_row)

        if missing_days or duplicates or invalid_dates or outliers or cliffs:
            issues.append(summary_row)

    summary_fields = [
        "symbol",
        "file",
        "rows",
        "start",
        "end",
        "expected_days",
        "missing_days",
        "missing_ratio",
        "duplicates",
        "invalid_dates",
        "outlier_returns",
        "cliff_returns",
        "max_abs_return",
        "filled_days",
        "sanitized_cliffs",
    ]
    _write_csv(summary_path, summaries, summary_fields)
    _write_csv(issues_path, issues, summary_fields)

    report = {
        "files": len(summaries),
        "rows": total_rows,
        "missing_days": total_missing,
        "duplicates": total_duplicates,
        "outliers": total_outliers,
        "cliffs": total_cliffs,
        "fixed_files": total_fixed,
        "summary_path": str(summary_path),
        "issues_path": str(issues_path),
    }
    (output_dir / "price_quality_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
