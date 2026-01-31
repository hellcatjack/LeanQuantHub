from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _baseline_path(root: Path) -> Path:
    return root / "positions_baseline.json"


def _parse_time(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value)
    return text


def ensure_positions_baseline(root: Path, payload: dict) -> dict:
    path = _baseline_path(root)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    source_detail = payload.get("source_detail")
    stale = bool(payload.get("stale", True))
    if source_detail != "ib_holdings" or stale:
        return {"created_at": None, "items": []}

    items = []
    for item in payload.get("items") or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        position = float(item.get("position") or 0.0)
        if position == 0:
            continue
        avg_cost = float(item.get("avg_cost") or item.get("avgCost") or 0.0)
        items.append({"symbol": symbol, "position": position, "avg_cost": avg_cost})

    baseline = {
        "created_at": _parse_time(payload.get("updated_at") or payload.get("refreshed_at")),
        "items": items,
    }
    path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline
