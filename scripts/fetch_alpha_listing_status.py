#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.job_lock import JobLock  # noqa: E402

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


def _resolve_api_key(value: str | None) -> str:
    if value:
        return value.strip()
    for key in ("ALPHA_VANTAGE_API_KEY", "ALPHAVANTAGE_API_KEY"):
        env_value = os.getenv(key)
        if env_value:
            return env_value.strip()
    return ""


def _validate_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not re.match(r"^\\d{4}-\\d{2}-\\d{2}$", text):
        raise ValueError("date must be YYYY-MM-DD")
    return text


def _fetch_listing_status(api_key: str, state: str, date: str | None) -> bytes:
    params = {"function": "LISTING_STATUS", "apikey": api_key}
    if state:
        params["state"] = state
    if date:
        params["date"] = date
    url = f"https://www.alphavantage.co/query?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "stocklean/1.0"})
    with urlopen(request, timeout=60) as handle:
        payload = handle.read()
    if payload[:1] == b"{":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            decoded = {"error": payload[:200].decode("utf-8", "ignore")}
        raise RuntimeError(f"alpha error: {decoded}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="active", choices=("active", "delisted"))
    parser.add_argument("--date", default="")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    api_key = _resolve_api_key(args.api_key)
    if not api_key:
        print("Missing API key. Set ALPHA_VANTAGE_API_KEY or pass --api-key.", file=sys.stderr)
        return 2

    date = _validate_date(args.date) if args.date else None
    data_root = _resolve_data_root(args.data_root)
    lock_handle = _acquire_lock(data_root)
    if not lock_handle:
        print("alpha_lock_busy", file=sys.stderr)
        return 3
    try:
        payload = _fetch_listing_status(api_key, args.state, date)
        if args.output:
            output_path = Path(args.output).expanduser()
            if not output_path.is_absolute():
                output_path = data_root / output_path
        else:
            suffix = date or "latest"
            output_path = data_root / "universe" / f"alpha_listing_status_{args.state}_{suffix}.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        print(f"saved: {output_path}")
        return 0
    finally:
        _release_lock(lock_handle)


if __name__ == "__main__":
    raise SystemExit(main())
