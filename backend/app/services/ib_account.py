from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.ib_settings import get_or_create_ib_settings
from app.services.lean_bridge_reader import read_account_summary, read_positions


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _normalize_items(raw_items: Any) -> dict[str, object]:
    if isinstance(raw_items, dict):
        return raw_items
    items: dict[str, object] = {}
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            items[str(name)] = item.get("value")
    return items


def get_account_summary(session, *, mode: str, full: bool, force_refresh: bool = False) -> dict[str, object]:
    payload = read_account_summary(_resolve_bridge_root())
    items = _normalize_items(payload.get("items"))
    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
    stale = bool(payload.get("stale", True))
    source = payload.get("source") or "lean_bridge"
    return {
        "items": items,
        "refreshed_at": refreshed_at,
        "source": source,
        "stale": stale,
        "full": full,
    }


def get_account_positions(session, *, mode: str, force_refresh: bool = False) -> dict[str, object]:
    payload = read_positions(_resolve_bridge_root())
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if "position" not in normalized and "quantity" in normalized:
            normalized["position"] = normalized.get("quantity")
        if (
            normalized.get("market_price") is None
            and normalized.get("market_value") is not None
            and normalized.get("position") not in (None, 0, 0.0)
        ):
            try:
                normalized["market_price"] = float(normalized["market_value"]) / float(
                    normalized["position"]
                )
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        items.append(normalized)
    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
    stale = bool(payload.get("stale", True))
    return {"items": items, "refreshed_at": refreshed_at, "stale": stale}


def fetch_account_summary(session) -> dict[str, float | str | None]:
    settings_row = get_or_create_ib_settings(session)
    mode = settings_row.mode or "paper"
    summary = get_account_summary(session, mode=mode, full=False, force_refresh=False)
    items = summary.get("items") if isinstance(summary.get("items"), dict) else {}
    cash_available = items.get("AvailableFunds") or items.get("CashBalance") or items.get("TotalCashValue")
    if isinstance(cash_available, str):
        try:
            cash_available = float(cash_available)
        except ValueError:
            pass
    output: dict[str, float | str | None] = dict(items)
    output["cash_available"] = cash_available
    return output
