from __future__ import annotations

import json
from pathlib import Path

BRIDGE_ROOT = Path("/app/stocklean/artifacts/lean_bridge")
CACHE_ROOT = Path("/app/stocklean/data/lean_bridge/cache")


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_bridge_cache() -> None:
    account = _read_json(BRIDGE_ROOT / "account_summary.json")
    positions = _read_json(BRIDGE_ROOT / "positions.json")
    quotes = _read_json(BRIDGE_ROOT / "quotes.json")
    if account is not None:
        _write_json(CACHE_ROOT / "account_summary.json", account)
    if positions is not None:
        _write_json(CACHE_ROOT / "positions.json", positions)
    if quotes is not None:
        _write_json(CACHE_ROOT / "quotes.json", quotes)
