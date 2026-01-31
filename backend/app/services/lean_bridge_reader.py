from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings

_HEARTBEAT_STALE_SECONDS = 10


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    text = ts.replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        tz = ""
        tz_index = None
        for sep in ("+", "-"):
            idx = tail.find(sep)
            if idx > 0:
                tz_index = idx
                break
        if tz_index is not None:
            frac = tail[:tz_index]
            tz = tail[tz_index:]
        else:
            frac = tail
        if len(frac) > 6:
            frac = frac[:6]
        text = f"{head}.{frac}{tz}"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def read_bridge_payload(root: Path, filename: str) -> dict | None:
    path = root / filename
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    return data


def parse_bridge_timestamp(payload: dict | None, keys: list[str]) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            parsed = _parse_iso(value)
            if parsed:
                return parsed
    return None


def _resolve_stale_seconds() -> int:
    try:
        return int(settings.lean_bridge_heartbeat_timeout_seconds)
    except (TypeError, ValueError):
        return _HEARTBEAT_STALE_SECONDS


def _is_stale(heartbeat: datetime | None, *, stale_seconds: int | None = None) -> bool:
    if heartbeat is None:
        return True
    now = datetime.now(timezone.utc)
    timeout = stale_seconds if stale_seconds is not None else _resolve_stale_seconds()
    return now - heartbeat > timedelta(seconds=timeout)


def read_bridge_status(root: Path) -> dict:
    path = root / "lean_bridge_status.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"status": "missing", "stale": True}
    heartbeat = _parse_iso(str(data.get("last_heartbeat") or ""))
    data.setdefault("status", "ok")
    data["stale"] = _is_stale(heartbeat)
    return data


def read_account_summary(root: Path) -> dict:
    path = root / "account_summary.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"items": [], "stale": True}
    data.setdefault("items", [])
    data.setdefault("stale", False)
    return data


def read_positions(root: Path) -> dict:
    path = root / "positions.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"items": [], "stale": True}
    data.setdefault("items", [])
    data.setdefault("stale", False)
    return data


def read_quotes(root: Path) -> dict:
    path = root / "quotes.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"items": [], "stale": True}
    data.setdefault("items", [])
    data.setdefault("stale", False)
    return data
