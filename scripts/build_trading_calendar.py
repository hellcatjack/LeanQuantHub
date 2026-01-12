#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from trading_calendar import (
    load_trading_calendar_config,
    resolve_data_root,
    trading_calendar_csv_path,
    trading_calendar_dir,
    trading_calendar_meta_path,
)


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


def _format_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _load_existing_rows(path: Path) -> dict[date, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[date, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = _parse_date(row.get("date"))
            if not parsed:
                continue
            rows[parsed] = row
    return rows


def _write_calendar(path: Path, rows: dict[date, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "session", "is_trading_day", "is_early_close"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for day in sorted(rows):
            row = rows[day]
            writer.writerow(
                {
                    "date": row.get("date") or _format_date(day),
                    "session": row.get("session") or "regular",
                    "is_trading_day": row.get("is_trading_day") or "1",
                    "is_early_close": row.get("is_early_close") or "0",
                }
            )


def _build_schedule(exchange: str, start: date, end: date) -> dict[date, dict[str, str]]:
    try:
        import exchange_calendars as xcals
    except ImportError as exc:
        raise SystemExit(
            "missing exchange_calendars. Install with: pip install exchange-calendars"
        ) from exc

    calendar = xcals.get_calendar(exchange)
    cal_start = getattr(calendar, "first_session", None)
    if cal_start is not None:
        cal_start_date = cal_start.date()
        if start < cal_start_date:
            start = cal_start_date
    cal_end = getattr(calendar, "last_session", None)
    if cal_end is not None:
        cal_end_date = cal_end.date()
        if end > cal_end_date:
            end = cal_end_date
    if start > end:
        return {}
    sessions = calendar.sessions_in_range(start, end)
    if len(sessions) == 0:
        return {}
    try:
        early_idx = calendar.early_closes
        early_days = {
            ts.date()
            for ts in early_idx
            if (ts.date() >= start and ts.date() <= end)
        }
    except Exception:
        early_days = set()

    rows: dict[date, dict[str, str]] = {}
    for ts in sessions:
        day = ts.date()
        rows[day] = {
            "date": _format_date(day),
            "session": "regular",
            "is_trading_day": "1",
            "is_early_close": "1" if day in early_days else "0",
        }
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Build trading calendar")
    parser.add_argument("--data-root", default="", help="DATA_ROOT override")
    parser.add_argument("--exchange", default="", help="exchange code, e.g., XNYS")
    parser.add_argument("--start", default="", help="start date YYYY-MM-DD")
    parser.add_argument("--end", default="", help="end date YYYY-MM-DD")
    parser.add_argument("--refresh-days", default="", help="refresh window days")
    args = parser.parse_args()

    data_root = resolve_data_root(args.data_root)
    config = load_trading_calendar_config(data_root)
    exchange = (args.exchange or config.get("exchange") or "XNYS").strip() or "XNYS"

    start = _parse_date(args.start) or _parse_date(config.get("start_date"))
    if not start:
        start = date(1990, 1, 1)
    end = _parse_date(args.end) or _parse_date(config.get("end_date"))
    if not end:
        end = date.today() + timedelta(days=365)

    refresh_days = args.refresh_days or config.get("refresh_days")
    try:
        refresh_days_val = int(refresh_days) if str(refresh_days).strip() else 0
    except (TypeError, ValueError):
        refresh_days_val = 0

    calendar_path = trading_calendar_csv_path(data_root, exchange)
    existing_rows = _load_existing_rows(calendar_path)
    if refresh_days_val > 0 and existing_rows:
        last_day = max(existing_rows)
        refresh_start = last_day - timedelta(days=refresh_days_val)
        if refresh_start > start:
            start = refresh_start

    new_rows = _build_schedule(exchange, start, end)
    merged_rows = {**existing_rows, **new_rows}
    _write_calendar(calendar_path, merged_rows)

    meta_path = trading_calendar_meta_path(data_root)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_payload = {
        "source": "exchange_calendars",
        "exchange": exchange,
        "start_date": min(merged_rows).strftime("%Y-%m-%d") if merged_rows else None,
        "end_date": max(merged_rows).strftime("%Y-%m-%d") if merged_rows else None,
        "generated_at": datetime.utcnow().isoformat(),
        "sessions": len(merged_rows),
        "path": str(calendar_path),
    }
    meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
