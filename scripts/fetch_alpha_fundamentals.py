#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ALPHA_FUNCTIONS = {
    "OVERVIEW": "overview.json",
    "INCOME_STATEMENT": "income_statement.json",
    "BALANCE_SHEET": "balance_sheet.json",
    "CASH_FLOW": "cash_flow.json",
    "EARNINGS": "earnings.json",
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


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'").strip('"')
    return env


def _resolve_api_key() -> str:
    key = (os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip()
    if key:
        return key
    env_path = Path(__file__).resolve().parents[1] / "backend" / ".env"
    env = _load_env(env_path)
    return (env.get("ALPHA_VANTAGE_API_KEY") or "").strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _load_symbols_from_csv(path: Path) -> list[str]:
    if not path.exists():
        return []
    symbols = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol:
                symbols.append(symbol)
    return symbols


def _load_symbols_from_pit(
    pit_dir: Path, start: datetime | None, end: datetime | None
) -> list[str]:
    if not pit_dir.exists():
        return []
    symbols: set[str] = set()
    for path in pit_dir.glob("pit_*.csv"):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                snapshot_raw = (row.get("snapshot_date") or "").strip()
                snapshot_dt = _parse_date(snapshot_raw)
                if start and snapshot_dt and snapshot_dt < start:
                    continue
                if end and snapshot_dt and snapshot_dt > end:
                    continue
                symbol = (row.get("symbol") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
    return sorted(symbols)


def _is_rate_limited(payload: dict) -> bool:
    note = str(payload.get("Note") or payload.get("Information") or payload.get("Error Message") or "")
    lowered = note.lower()
    if not lowered:
        return False
    return any(
        key in lowered
        for key in (
            "call frequency",
            "standard api",
            "premium",
            "limit",
            "rate",
            "thank you for using alpha vantage",
        )
    )


def _fetch_alpha_json(api_key: str, function: str, symbol: str) -> dict:
    params = {"function": function, "symbol": symbol, "apikey": api_key}
    url = f"https://www.alphavantage.co/query?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "stocklean/1.0"})
    with urlopen(request, timeout=60) as handle:
        payload = handle.read()
    return json.loads(payload.decode("utf-8", errors="ignore"))


def _should_refresh(path: Path, refresh_days: int) -> bool:
    if refresh_days <= 0:
        return True
    if not path.exists():
        return True
    mtime = datetime.utcfromtimestamp(path.stat().st_mtime)
    return mtime <= datetime.utcnow() - timedelta(days=refresh_days)


def _write_status(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["symbol", "status", "updated_at", "message"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _write_progress(path: Path | None, payload: dict[str, object]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--symbol-file", default="")
    parser.add_argument("--from-pit", action="store_true")
    parser.add_argument("--pit-dir", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--refresh-days", type=int, default=30)
    parser.add_argument("--min-delay", type=float, default=0.8)
    parser.add_argument("--rate-limit-sleep", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--rate-limit-retries", type=int, default=3)
    parser.add_argument("--progress-path", default="")
    args = parser.parse_args()

    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError("missing ALPHA_VANTAGE_API_KEY")

    data_root = _resolve_data_root(args.data_root)
    fundamentals_root = data_root / "fundamentals" / "alpha"
    pit_dir = Path(args.pit_dir) if args.pit_dir else data_root / "universe" / "pit_weekly"
    if not pit_dir.is_absolute():
        pit_dir = data_root / pit_dir

    symbols: list[str] = []
    if args.symbols.strip():
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    elif args.from_pit:
        start = _parse_date(args.start) if args.start else None
        end = _parse_date(args.end) if args.end else None
        symbols = _load_symbols_from_pit(pit_dir, start, end)
    else:
        symbol_file = args.symbol_file.strip()
        if not symbol_file:
            symbol_file = str(data_root / "universe" / "alpha_symbol_life.csv")
        path = Path(symbol_file)
        if not path.is_absolute():
            path = data_root / path
        symbols = _load_symbols_from_csv(path)

    if not symbols:
        raise RuntimeError("no symbols to fetch")

    offset = max(args.offset, 0)
    limit = max(args.limit, 0)
    target_symbols = symbols[offset:]
    if limit:
        target_symbols = target_symbols[:limit]

    progress_path = Path(args.progress_path).expanduser().resolve() if args.progress_path else None
    statuses: list[dict[str, str]] = []

    total = len(target_symbols)
    completed: set[str] = set()
    ok_count = 0
    partial_count = 0
    rate_limited_events = 0
    rate_limit_counts: dict[str, int] = defaultdict(int)
    messages: dict[str, list[str]] = defaultdict(list)
    queue: deque[str] = deque(target_symbols)

    def update_progress(current_symbol: str | None = None) -> None:
        _write_progress(
            progress_path,
            {
                "stage": "fetch",
                "total": total,
                "done": len(completed),
                "pending": max(total - len(completed), 0),
                "ok": ok_count,
                "partial": partial_count,
                "rate_limited": rate_limited_events,
                "current_symbol": current_symbol or "",
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

    update_progress()

    while queue:
        symbol = queue.popleft()
        if symbol in completed:
            continue
        symbol_dir = fundamentals_root / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        status_message = messages[symbol]
        ok = True
        rate_limited = False
        for function, filename in ALPHA_FUNCTIONS.items():
            target_path = symbol_dir / filename
            if not _should_refresh(target_path, args.refresh_days):
                continue
            attempt = 0
            while True:
                attempt += 1
                payload = _fetch_alpha_json(api_key, function, symbol)
                if _is_rate_limited(payload):
                    rate_limited_events += 1
                    if attempt >= args.max_retries:
                        status_message.append(f"{function}:rate_limited")
                        ok = False
                        rate_limited = True
                        break
                    time.sleep(args.rate_limit_sleep)
                    continue
                if "Error Message" in payload:
                    status_message.append(f"{function}:error")
                    ok = False
                    break
                target_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                break
            if rate_limited or not ok:
                break
            time.sleep(max(args.min_delay, 0))
        if rate_limited:
            rate_limit_counts[symbol] += 1
            if rate_limit_counts[symbol] <= max(args.rate_limit_retries, 0):
                queue.append(symbol)
                update_progress(symbol)
                time.sleep(args.rate_limit_sleep)
                continue
        completed.add(symbol)
        if ok:
            ok_count += 1
        else:
            partial_count += 1
        statuses.append(
            {
                "symbol": symbol,
                "status": "ok" if ok else "partial",
                "updated_at": datetime.utcnow().isoformat(),
                "message": ";".join(status_message),
            }
        )
        update_progress(symbol)

    status_path = fundamentals_root / "fundamentals_status.csv"
    _write_status(status_path, statuses)
    print(f"status: {status_path}")
    print(f"symbols: {len(target_symbols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
