from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.lean_bridge import CACHE_ROOT, refresh_bridge_cache


def _read_json(name: str) -> object | None:
    path = CACHE_ROOT / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def get_account_summary(
    session=None,
    *,
    mode: str = "paper",
    full: bool = False,
    force_refresh: bool = False,
) -> dict[str, object]:
    refresh_bridge_cache()
    payload = _read_json("account_summary.json")
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), dict):
            items = payload.get("items") or {}
            return {
                "items": items,
                "refreshed_at": payload.get("refreshed_at"),
                "source": payload.get("source"),
                "stale": bool(payload.get("stale", False)),
                "full": bool(payload.get("full", full)),
            }
        return {
            "items": payload,
            "refreshed_at": None,
            "source": "lean_bridge",
            "stale": False,
            "full": bool(full),
        }
    return {
        "items": {},
        "refreshed_at": None,
        "source": None,
        "stale": True,
        "full": bool(full),
    }


def get_account_positions(session=None, *, mode: str = "paper", force_refresh: bool = False) -> dict[str, object]:
    refresh_bridge_cache()
    payload = _read_json("positions.json")
    if isinstance(payload, list):
        return {"items": payload, "refreshed_at": None, "stale": False}
    return {"items": [], "refreshed_at": None, "stale": True}


def fetch_account_summary(session) -> dict[str, float | str | None]:
    summary = get_account_summary(session, mode="paper", full=False, force_refresh=False)
    if isinstance(summary.get("items"), dict):
        items: dict[str, Any] = summary.get("items") or {}
    else:
        items = summary
    cash_available = items.get("AvailableFunds") or items.get("CashBalance") or items.get("TotalCashValue")
    return {
        "NetLiquidation": items.get("NetLiquidation"),
        "AvailableFunds": cash_available,
        "TotalCashValue": items.get("TotalCashValue"),
        "CashBalance": items.get("CashBalance"),
    }
