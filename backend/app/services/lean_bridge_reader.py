from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_stale(heartbeat: datetime | None) -> bool:
    if heartbeat is None:
        return True
    now = datetime.now(timezone.utc)
    return now - heartbeat > timedelta(seconds=_HEARTBEAT_STALE_SECONDS)


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
