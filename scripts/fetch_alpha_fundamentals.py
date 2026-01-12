#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.job_lock import JobLock  # noqa: E402

ALPHA_FUNCTIONS = {
    "OVERVIEW": "overview.json",
    "INCOME_STATEMENT": "income_statement.json",
    "BALANCE_SHEET": "balance_sheet.json",
    "CASH_FLOW": "cash_flow.json",
    "EARNINGS": "earnings.json",
    "SHARES_OUTSTANDING": "shares_outstanding.json",
}
DEFAULT_CANCEL_EXIT_CODE = 130
DEFAULT_AUTO_TUNE = True
DEFAULT_MIN_DELAY_SECONDS = 0.12
DEFAULT_MIN_DELAY_FLOOR_SECONDS = 0.1
DEFAULT_MIN_DELAY_CEIL_SECONDS = 2.0
DEFAULT_TUNE_STEP_SECONDS = 0.02
DEFAULT_TUNE_WINDOW_SECONDS = 60.0
DEFAULT_TUNE_TARGET_RATIO_LOW = 0.9
DEFAULT_TUNE_TARGET_RATIO_HIGH = 1.05
DEFAULT_TUNE_COOLDOWN_SECONDS = 10.0
DEFAULT_TUNE_SUSPEND_SECONDS = 60.0
DEFAULT_RATE_LIMIT_SLEEP = 10.0
DEFAULT_MAX_RPM = 154.0
DEFAULT_RPM_FLOOR = 90.0
DEFAULT_RPM_CEIL = 170.0
DEFAULT_RPM_STEP_DOWN = 5.0
DEFAULT_RPM_STEP_UP = 2.0
DEFAULT_RATE_LIMIT_STEP_SECONDS = 0.1


class AlphaRateLimitError(RuntimeError):
    pass


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


def _acquire_lock(data_root: Path) -> JobLock | None:
    lock = JobLock("alpha_fetch", data_root)
    if not lock.acquire():
        return None
    return lock


def _release_lock(lock: JobLock | None) -> None:
    if not lock:
        return
    lock.release()


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


def _coerce_float(value: object, default: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if num > 0 else default


def _coerce_int(value: object, default: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return num if num > 0 else default


def _coerce_bool(value: object, default: bool) -> bool:
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


def _should_penalize_rate_limit(
    now: float, last_rate_limit_at: float | None, rate_limit_sleep: float
) -> bool:
    if last_rate_limit_at is None:
        return True
    return (now - last_rate_limit_at) >= 2 * max(rate_limit_sleep, 0.0)


def _resolve_rate_config_path(value: str | None, data_root: Path) -> Path:
    if value:
        path = Path(value).expanduser()
        return path if path.is_absolute() else data_root / path
    return data_root / "config" / "alpha_rate.json"


class RateConfig:
    def __init__(self, path: Path, defaults: dict[str, float | int | bool]):
        self.path = path
        self.defaults = defaults
        self._cached: dict[str, float | int | bool] = dict(defaults)
        self._mtime: float | None = None
        self._last_tune_at: float = 0.0

    def refresh(self) -> None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._cached = dict(self.defaults)
            self._mtime = None
            self._apply_limits()
            return
        if self._mtime is not None and stat.st_mtime == self._mtime:
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._cached = dict(self.defaults)
            self._mtime = stat.st_mtime
            self._apply_limits()
            return
        if isinstance(payload, dict):
            for key in self.defaults:
                if key in payload and payload[key] is not None:
                    self._cached[key] = payload[key]
        self._mtime = stat.st_mtime
        self._apply_limits()

    def _apply_limits(self) -> None:
        max_rpm = _coerce_float(self._cached.get("max_rpm"), 0.0)
        rpm_floor = _coerce_float(self._cached.get("rpm_floor"), DEFAULT_RPM_FLOOR)
        rpm_ceil = _coerce_float(self._cached.get("rpm_ceil"), max_rpm or rpm_floor)
        if rpm_ceil < rpm_floor:
            rpm_ceil = rpm_floor
        max_rpm = min(max(max_rpm, rpm_floor), rpm_ceil)
        self._cached["max_rpm"] = max_rpm
        self._cached["rpm_floor"] = rpm_floor
        self._cached["rpm_ceil"] = rpm_ceil
        self._cached["rpm_step_down"] = _coerce_float(
            self._cached.get("rpm_step_down"), DEFAULT_RPM_STEP_DOWN
        )
        self._cached["rpm_step_up"] = _coerce_float(
            self._cached.get("rpm_step_up"), DEFAULT_RPM_STEP_UP
        )
        min_delay = _coerce_float(self._cached.get("min_delay_seconds"), 0.0)
        floor = _coerce_float(
            self._cached.get("min_delay_floor_seconds"), DEFAULT_MIN_DELAY_FLOOR_SECONDS
        )
        ceil = _coerce_float(
            self._cached.get("min_delay_ceil_seconds"), DEFAULT_MIN_DELAY_CEIL_SECONDS
        )
        if ceil < floor:
            ceil = floor
        min_delay = min(max(min_delay, floor), ceil)
        self._cached["min_delay_seconds"] = min_delay
        self._cached["min_delay_floor_seconds"] = floor
        self._cached["min_delay_ceil_seconds"] = ceil
        self._cached["auto_tune"] = _coerce_bool(
            self._cached.get("auto_tune"), DEFAULT_AUTO_TUNE
        )
        self._cached["tune_step_seconds"] = _coerce_float(
            self._cached.get("tune_step_seconds"), DEFAULT_TUNE_STEP_SECONDS
        )
        self._cached["tune_window_seconds"] = _coerce_float(
            self._cached.get("tune_window_seconds"), DEFAULT_TUNE_WINDOW_SECONDS
        )
        self._cached["tune_target_ratio_low"] = _coerce_float(
            self._cached.get("tune_target_ratio_low"), DEFAULT_TUNE_TARGET_RATIO_LOW
        )
        self._cached["tune_target_ratio_high"] = _coerce_float(
            self._cached.get("tune_target_ratio_high"), DEFAULT_TUNE_TARGET_RATIO_HIGH
        )
        self._cached["tune_cooldown_seconds"] = _coerce_float(
            self._cached.get("tune_cooldown_seconds"), DEFAULT_TUNE_COOLDOWN_SECONDS
        )
        derived = 0.0
        if max_rpm > 0:
            derived = 60.0 / max_rpm
        self._cached["effective_min_delay_seconds"] = max(min_delay, derived)

    def get(self, key: str) -> float | int | bool:
        return self._cached.get(key, self.defaults.get(key, 0))

    def maybe_auto_tune(
        self, rate_per_min: float, target_rpm: float, rate_limited_recent: bool
    ) -> dict[str, float | str] | None:
        auto_tune = _coerce_bool(self._cached.get("auto_tune"), False)
        if not auto_tune or target_rpm <= 0:
            return None
        now = time.monotonic()
        cooldown = _coerce_float(
            self._cached.get("tune_cooldown_seconds"), DEFAULT_TUNE_COOLDOWN_SECONDS
        )
        if now - self._last_tune_at < cooldown:
            return None
        step = _coerce_float(
            self._cached.get("tune_step_seconds"), DEFAULT_TUNE_STEP_SECONDS
        )
        floor = _coerce_float(
            self._cached.get("min_delay_floor_seconds"), DEFAULT_MIN_DELAY_FLOOR_SECONDS
        )
        ceil = _coerce_float(
            self._cached.get("min_delay_ceil_seconds"), DEFAULT_MIN_DELAY_CEIL_SECONDS
        )
        if ceil < floor:
            ceil = floor
        ratio_low = _coerce_float(
            self._cached.get("tune_target_ratio_low"), DEFAULT_TUNE_TARGET_RATIO_LOW
        )
        ratio_high = _coerce_float(
            self._cached.get("tune_target_ratio_high"), DEFAULT_TUNE_TARGET_RATIO_HIGH
        )
        if ratio_high < ratio_low:
            ratio_high = ratio_low
        current = _coerce_float(self._cached.get("min_delay_seconds"), DEFAULT_MIN_DELAY_SECONDS)
        effective_delay = _coerce_float(
            self._cached.get("effective_min_delay_seconds"), current
        )
        current_rpm = _coerce_float(self._cached.get("max_rpm"), 0.0)
        rpm_floor = _coerce_float(self._cached.get("rpm_floor"), DEFAULT_RPM_FLOOR)
        rpm_ceil = _coerce_float(self._cached.get("rpm_ceil"), current_rpm or rpm_floor)
        rpm_step_down = _coerce_float(
            self._cached.get("rpm_step_down"), DEFAULT_RPM_STEP_DOWN
        )
        rpm_step_up = _coerce_float(self._cached.get("rpm_step_up"), DEFAULT_RPM_STEP_UP)
        ratio = rate_per_min / target_rpm if target_rpm > 0 else 0.0
        reason = ""
        rpm_reason = ""
        next_delay = current
        next_rpm = current_rpm
        if rate_limited_recent:
            reason = "rate_limited"
            next_delay = current + step
            if rpm_step_down > 0 and current_rpm > rpm_floor:
                rpm_reason = "rpm_down"
                next_rpm = max(current_rpm - rpm_step_down, rpm_floor)
        elif ratio < ratio_low:
            reason = "below_target"
            delay_gap = effective_delay - current
            if delay_gap + 1e-6 >= step:
                if rpm_step_up > 0 and current_rpm < rpm_ceil:
                    rpm_reason = "rpm_up"
                    next_rpm = min(current_rpm + rpm_step_up, rpm_ceil)
            else:
                next_delay = current - step
        elif ratio > ratio_high:
            reason = "above_target"
            next_delay = current + step
        if not reason and not rpm_reason:
            return None
        next_delay = min(max(next_delay, floor), ceil)
        delay_changed = abs(next_delay - current) >= 1e-6
        rpm_changed = abs(next_rpm - current_rpm) >= 1e-6
        if not delay_changed and not rpm_changed:
            return None
        if delay_changed:
            self._cached["min_delay_seconds"] = next_delay
        if rpm_changed:
            self._cached["max_rpm"] = next_rpm
        self._last_tune_at = now
        self._write_config()
        self.refresh()
        reason_parts = [part for part in (reason, rpm_reason) if part]
        payload: dict[str, float | str] = {"reason": ",".join(reason_parts)}
        if delay_changed:
            payload["min_delay_seconds"] = next_delay
        if rpm_changed:
            payload["max_rpm"] = next_rpm
        return payload

    def apply_rate_limit_penalty(self) -> dict[str, float | str] | None:
        auto_tune = _coerce_bool(self._cached.get("auto_tune"), False)
        if not auto_tune:
            return None
        now = time.monotonic()
        step = _coerce_float(self._cached.get("tune_step_seconds"), DEFAULT_TUNE_STEP_SECONDS)
        step = max(step, DEFAULT_RATE_LIMIT_STEP_SECONDS)
        floor = _coerce_float(
            self._cached.get("min_delay_floor_seconds"), DEFAULT_MIN_DELAY_FLOOR_SECONDS
        )
        ceil = _coerce_float(
            self._cached.get("min_delay_ceil_seconds"), DEFAULT_MIN_DELAY_CEIL_SECONDS
        )
        if ceil < floor:
            ceil = floor
        current_delay = _coerce_float(
            self._cached.get("min_delay_seconds"), DEFAULT_MIN_DELAY_SECONDS
        )
        next_delay = min(max(current_delay + step, floor), ceil)
        current_rpm = _coerce_float(self._cached.get("max_rpm"), 0.0)
        rpm_floor = _coerce_float(self._cached.get("rpm_floor"), DEFAULT_RPM_FLOOR)
        rpm_step_down = _coerce_float(
            self._cached.get("rpm_step_down"), DEFAULT_RPM_STEP_DOWN
        )
        next_rpm = current_rpm
        if rpm_step_down > 0 and current_rpm > rpm_floor:
            next_rpm = max(current_rpm - rpm_step_down, rpm_floor)
        delay_changed = abs(next_delay - current_delay) >= 1e-6
        rpm_changed = abs(next_rpm - current_rpm) >= 1e-6
        if not delay_changed and not rpm_changed:
            return None
        if delay_changed:
            self._cached["min_delay_seconds"] = next_delay
        if rpm_changed:
            self._cached["max_rpm"] = next_rpm
        self._last_tune_at = now
        self._write_config()
        self.refresh()
        reason_parts = ["rate_limited"]
        if rpm_changed:
            reason_parts.append("rpm_down")
        payload: dict[str, float | str] = {"reason": ",".join(reason_parts)}
        if delay_changed:
            payload["min_delay_seconds"] = next_delay
        if rpm_changed:
            payload["max_rpm"] = next_rpm
        return payload

    def _write_config(self) -> None:
        payload = {
            key: self._cached.get(key, self.defaults.get(key)) for key in self.defaults
        }
        payload["updated_at"] = datetime.utcnow().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)


def _fetch_alpha_json(api_key: str, function: str, symbol: str) -> dict:
    params = {"function": function, "symbol": symbol, "apikey": api_key}
    url = f"https://www.alphavantage.co/query?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "stocklean/1.0"})
    try:
        with urlopen(request, timeout=60) as handle:
            payload = handle.read()
    except HTTPError as exc:
        if exc.code == 429:
            raise AlphaRateLimitError("rate_limited") from exc
        raise
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
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    tmp_path.replace(path)


def _append_status(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["symbol", "status", "updated_at", "message"]
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fields})


def _load_status(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            rows[symbol] = dict(row)
    return rows


def _write_progress(path: Path | None, payload: dict[str, object]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _write_cancel_progress(
    path: Path | None,
    total: int,
    done: int,
    ok: int,
    partial: int,
    rate_limited: int,
) -> None:
    if not path:
        return
    _write_progress(
        path,
        {
            "stage": "canceled",
            "status": "canceled",
            "total": total,
            "done": done,
            "pending": max(total - done, 0),
            "ok": ok,
            "partial": partial,
            "rate_limited": rate_limited,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )


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
    parser.add_argument("--min-delay", type=float, default=DEFAULT_MIN_DELAY_SECONDS)
    parser.add_argument("--rate-limit-sleep", type=float, default=DEFAULT_RATE_LIMIT_SLEEP)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--rate-limit-retries", type=int, default=3)
    parser.add_argument("--progress-path", default="")
    parser.add_argument("--status-path", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-path", default="")
    parser.add_argument("--cancel-path", default="")
    parser.add_argument("--rate-config", default="")
    parser.add_argument("--max-rpm", type=float, default=0)
    parser.add_argument("--auto-tune", action="store_true")
    parser.add_argument("--tune-window", type=float, default=0)
    parser.add_argument("--tune-step", type=float, default=0)
    parser.add_argument("--tune-floor", type=float, default=0)
    parser.add_argument("--tune-ceil", type=float, default=0)
    parser.add_argument("--tune-low", type=float, default=0)
    parser.add_argument("--tune-high", type=float, default=0)
    parser.add_argument("--tune-cooldown", type=float, default=0)
    parser.add_argument("--skip-lock", action="store_true")
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
    cancel_path = Path(args.cancel_path).expanduser().resolve() if args.cancel_path else None
    status_path = (
        Path(args.status_path).expanduser().resolve()
        if args.status_path
        else fundamentals_root / "fundamentals_status.csv"
    )
    status_map = _load_status(status_path)
    if args.resume:
        resume_path = (
            Path(args.resume_path).expanduser().resolve()
            if args.resume_path
            else status_path
        )
        resume_map = _load_status(resume_path)
        resume_ok = {
            symbol
            for symbol, row in resume_map.items()
            if (row.get("status") or "").lower() == "ok"
        }
        if resume_map and resume_path != status_path:
            status_map.update(resume_map)
            _write_status(status_path, [status_map[key] for key in sorted(status_map)])
        if resume_ok:
            target_symbols = [symbol for symbol in target_symbols if symbol not in resume_ok]
    rate_config_path = _resolve_rate_config_path(args.rate_config, data_root)
    defaults = {
        "max_rpm": args.max_rpm or DEFAULT_MAX_RPM,
        "rpm_floor": DEFAULT_RPM_FLOOR,
        "rpm_ceil": args.max_rpm or DEFAULT_RPM_CEIL,
        "rpm_step_down": DEFAULT_RPM_STEP_DOWN,
        "rpm_step_up": DEFAULT_RPM_STEP_UP,
        "min_delay_seconds": max(args.min_delay, 0.0),
        "rate_limit_sleep": max(args.rate_limit_sleep, 0.0),
        "rate_limit_retries": max(args.rate_limit_retries, 0),
        "max_retries": max(args.max_retries, 1),
        "auto_tune": bool(args.auto_tune),
        "min_delay_floor_seconds": (
            args.tune_floor
            if args.tune_floor > 0
            else DEFAULT_MIN_DELAY_FLOOR_SECONDS
        ),
        "min_delay_ceil_seconds": (
            args.tune_ceil if args.tune_ceil > 0 else DEFAULT_MIN_DELAY_CEIL_SECONDS
        ),
        "tune_step_seconds": (
            args.tune_step if args.tune_step > 0 else DEFAULT_TUNE_STEP_SECONDS
        ),
        "tune_window_seconds": (
            args.tune_window if args.tune_window > 0 else DEFAULT_TUNE_WINDOW_SECONDS
        ),
        "tune_target_ratio_low": (
            args.tune_low if args.tune_low > 0 else DEFAULT_TUNE_TARGET_RATIO_LOW
        ),
        "tune_target_ratio_high": (
            args.tune_high if args.tune_high > 0 else DEFAULT_TUNE_TARGET_RATIO_HIGH
        ),
        "tune_cooldown_seconds": (
            args.tune_cooldown
            if args.tune_cooldown > 0
            else DEFAULT_TUNE_COOLDOWN_SECONDS
        ),
    }
    rate_config = RateConfig(rate_config_path, defaults)
    last_request_at: float | None = None
    request_times: deque[float] = deque()
    last_rate_limit_at: float | None = None
    last_tune_action: dict[str, float | str] | None = None
    tune_suspend_until = time.monotonic() + DEFAULT_TUNE_SUSPEND_SECONDS

    total = len(target_symbols)
    completed: set[str] = set()
    ok_count = 0
    partial_count = 0
    rate_limited_events = 0
    rate_limit_counts: dict[str, int] = defaultdict(int)
    messages: dict[str, list[str]] = defaultdict(list)
    queue: deque[str] = deque(target_symbols)
    lock_handle = None
    if not args.skip_lock:
        lock_handle = _acquire_lock(data_root)
        if not lock_handle:
            raise RuntimeError("alpha_lock_busy")

    def is_canceled() -> bool:
        if not cancel_path:
            return False
        return cancel_path.exists()

    def handle_cancel() -> int:
        _write_cancel_progress(
            progress_path, total, len(completed), ok_count, partial_count, rate_limited_events
        )
        return DEFAULT_CANCEL_EXIT_CODE

    def suspend_tuning_after_resume(sleep_seconds: float) -> None:
        nonlocal tune_suspend_until
        resume_at = time.monotonic() + max(sleep_seconds, 0.0)
        tune_suspend_until = max(
            tune_suspend_until, resume_at + DEFAULT_TUNE_SUSPEND_SECONDS
        )

    def update_progress(current_symbol: str | None = None) -> None:
        rate_config.refresh()
        tune_window = _coerce_float(
            rate_config.get("tune_window_seconds"), DEFAULT_TUNE_WINDOW_SECONDS
        )
        window = tune_window if tune_window > 0 else DEFAULT_TUNE_WINDOW_SECONDS
        now = time.monotonic()
        while request_times and now - request_times[0] > window:
            request_times.popleft()
        rate_per_min = (len(request_times) * 60.0 / window) if window > 0 else 0.0
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
                "rate_per_min": rate_per_min,
                "target_rpm": float(rate_config.get("max_rpm") or 0.0) or None,
                "min_delay_seconds": float(rate_config.get("min_delay_seconds") or 0.0),
                "effective_min_delay_seconds": float(
                    rate_config.get("effective_min_delay_seconds") or 0.0
                ),
                "auto_tune": bool(rate_config.get("auto_tune") or False),
                "tune_window_seconds": window,
                "tune_action": last_tune_action or {},
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

    update_progress()

    try:
        if is_canceled():
            return handle_cancel()
        while queue:
            if is_canceled():
                return handle_cancel()
            symbol = queue.popleft()
            if symbol in completed:
                continue
            symbol_dir = fundamentals_root / symbol
            symbol_dir.mkdir(parents=True, exist_ok=True)
            status_message = messages[symbol]
            ok = True
            rate_limited = False
            for function, filename in ALPHA_FUNCTIONS.items():
                if is_canceled():
                    return handle_cancel()
                target_path = symbol_dir / filename
                if not _should_refresh(target_path, args.refresh_days):
                    continue
                attempt = 0
                while True:
                    if is_canceled():
                        return handle_cancel()
                    rate_config.refresh()
                    max_retries = int(rate_config.get("max_retries") or 1)
                    rate_limit_sleep = float(
                        rate_config.get("rate_limit_sleep") or DEFAULT_RATE_LIMIT_SLEEP
                    )
                    min_delay = float(rate_config.get("effective_min_delay_seconds") or 0.0)
                    attempt += 1
                    if last_request_at is not None:
                        elapsed = time.monotonic() - last_request_at
                        if elapsed < min_delay:
                            time.sleep(min_delay - elapsed)
                    try:
                        payload = _fetch_alpha_json(api_key, function, symbol)
                    except AlphaRateLimitError:
                        now = time.monotonic()
                        last_request_at = now
                        request_times.append(now)
                        rate_limited_events += 1
                        should_penalize = _should_penalize_rate_limit(
                            now, last_rate_limit_at, rate_limit_sleep
                        )
                        last_rate_limit_at = now
                        if should_penalize:
                            tuned = rate_config.apply_rate_limit_penalty()
                            if tuned:
                                last_tune_action = tuned
                        update_progress(symbol)
                        if attempt >= max_retries:
                            status_message.append(f"{function}:rate_limited")
                            ok = False
                            rate_limited = True
                            break
                        suspend_tuning_after_resume(rate_limit_sleep)
                        time.sleep(rate_limit_sleep)
                        continue
                    except Exception as exc:
                        last_request_at = time.monotonic()
                        request_times.append(last_request_at)
                        update_progress(symbol)
                        if attempt >= max_retries:
                            status_message.append(
                                f"{function}:network_error:{type(exc).__name__}"
                            )
                            ok = False
                            break
                        time.sleep(rate_limit_sleep)
                        continue
                    last_request_at = time.monotonic()
                    request_times.append(last_request_at)
                    if _is_rate_limited(payload):
                        rate_limited_events += 1
                        now = last_request_at
                        should_penalize = _should_penalize_rate_limit(
                            now, last_rate_limit_at, rate_limit_sleep
                        )
                        last_rate_limit_at = now
                        if should_penalize:
                            tuned = rate_config.apply_rate_limit_penalty()
                            if tuned:
                                last_tune_action = tuned
                        update_progress(symbol)
                        if attempt >= max_retries:
                            status_message.append(f"{function}:rate_limited")
                            ok = False
                            rate_limited = True
                            break
                        suspend_tuning_after_resume(rate_limit_sleep)
                        time.sleep(rate_limit_sleep)
                        continue
                    if "Error Message" in payload:
                        status_message.append(f"{function}:error")
                        ok = False
                        break
                    tmp_path = target_path.with_suffix(".tmp")
                    tmp_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    tmp_path.replace(target_path)
                    update_progress(symbol)
                    now = time.monotonic()
                    tune_window = _coerce_float(
                        rate_config.get("tune_window_seconds"), DEFAULT_TUNE_WINDOW_SECONDS
                    )
                    window = tune_window if tune_window > 0 else DEFAULT_TUNE_WINDOW_SECONDS
                    while request_times and now - request_times[0] > window:
                        request_times.popleft()
                    rate_per_min = (len(request_times) * 60.0 / window) if window > 0 else 0.0
                    target_rpm = float(rate_config.get("max_rpm") or 0.0) or 0.0
                    rate_limited_recent = (
                        last_rate_limit_at is not None
                        and (now - last_rate_limit_at) <= window
                    )
                    if now >= tune_suspend_until:
                        tuned = rate_config.maybe_auto_tune(
                            rate_per_min, target_rpm, rate_limited_recent
                        )
                        if tuned:
                            last_tune_action = tuned
                            update_progress(symbol)
                    break
                if rate_limited or not ok:
                    break
            if rate_limited:
                rate_limit_counts[symbol] += 1
                rate_config.refresh()
                limit_retries = int(rate_config.get("rate_limit_retries") or 0)
                rate_limit_sleep = float(
                    rate_config.get("rate_limit_sleep") or DEFAULT_RATE_LIMIT_SLEEP
                )
                if rate_limit_counts[symbol] <= limit_retries:
                    queue.append(symbol)
                    update_progress(symbol)
                    time.sleep(rate_limit_sleep)
                    continue
            completed.add(symbol)
            if ok:
                ok_count += 1
            else:
                partial_count += 1
            row = {
                "symbol": symbol,
                "status": "ok" if ok else "partial",
                "updated_at": datetime.utcnow().isoformat(),
                "message": ";".join(status_message),
            }
            status_map[symbol] = row
            _append_status(status_path, row)
            update_progress(symbol)
    finally:
        _release_lock(lock_handle)

    _write_status(status_path, [status_map[key] for key in sorted(status_map)])
    print(f"status: {status_path}")
    print(f"symbols: {len(target_symbols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
