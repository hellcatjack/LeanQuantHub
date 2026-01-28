from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.ib_settings import ensure_ib_client_id, get_or_create_ib_settings
from app.services.lean_bridge_reader import read_account_summary, read_positions, read_quotes


CORE_TAGS = (
    "NetLiquidation",
    "TotalCashValue",
    "AvailableFunds",
    "CashBalance",
)


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


def _filter_summary(raw: Any, *, full: bool) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    if full:
        return dict(raw)
    return {key: value for key, value in raw.items() if key in CORE_TAGS}


def build_account_summary_tags(*, full: bool) -> str:
    if full:
        return "All"
    return ",".join(CORE_TAGS)


def resolve_ib_account_settings(session):
    return get_or_create_ib_settings(session)


def iter_account_client_ids(base: int, *, attempts: int = 3):
    base_id = int(base)
    count = max(int(attempts), 0)
    for offset in range(count):
        yield base_id + offset


def get_account_summary(session, *, mode: str, full: bool, force_refresh: bool = False) -> dict[str, object]:
    payload = read_account_summary(_resolve_bridge_root())
    items = _filter_summary(_normalize_items(payload.get("items")), full=full)
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
    quotes_payload = read_quotes(_resolve_bridge_root())
    quote_items = quotes_payload.get("items") if isinstance(quotes_payload.get("items"), list) else []
    quote_prices: dict[str, float] = {}
    for item in quote_items:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not symbol:
            continue
        price = item.get("last")
        if price is None:
            bid = item.get("bid")
            ask = item.get("ask")
            if bid is not None and ask is not None:
                price = (float(bid) + float(ask)) / 2
            elif bid is not None:
                price = bid
            elif ask is not None:
                price = ask
        if price is None:
            continue
        try:
            quote_prices[str(symbol)] = float(price)
        except (TypeError, ValueError):
            continue
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if "position" not in normalized and "quantity" in normalized:
            normalized["position"] = normalized.get("quantity")
        symbol = normalized.get("symbol")
        position = normalized.get("position")
        avg_cost = normalized.get("avg_cost")
        market_price = normalized.get("market_price")
        quote_price = quote_prices.get(str(symbol)) if symbol is not None else None
        if (market_price is None or market_price == 0) and quote_price is not None:
            normalized["market_price"] = quote_price
            market_price = quote_price
        market_value = normalized.get("market_value")
        if (
            (market_value is None or market_value == 0)
            and market_price not in (None, 0, 0.0)
            and position not in (None, 0, 0.0)
        ):
            try:
                normalized["market_value"] = float(market_price) * float(position)
            except (TypeError, ValueError):
                pass
        unrealized = normalized.get("unrealized_pnl")
        if (
            (unrealized is None or unrealized == 0)
            and market_price not in (None, 0, 0.0)
            and avg_cost not in (None, 0, 0.0)
            and position not in (None, 0, 0.0)
        ):
            try:
                normalized["unrealized_pnl"] = (float(market_price) - float(avg_cost)) * float(position)
            except (TypeError, ValueError):
                pass
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
