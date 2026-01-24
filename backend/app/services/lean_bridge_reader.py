from __future__ import annotations

import json
from pathlib import Path


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_bridge_status(root: Path) -> dict:
    path = root / "lean_bridge_status.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"status": "missing", "stale": True}
    data.setdefault("status", "ok")
    data.setdefault("stale", False)
    return data


def read_account_summary(root: Path) -> dict:
    path = root / "account_summary.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"items": [], "stale": True}
    data.setdefault("items", [])
    data.setdefault("stale", False)
    return data
