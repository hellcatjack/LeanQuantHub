from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.ib_read_session import get_ib_read_session
from app.services.ib_settings import get_or_create_ib_settings, resolve_ib_api_mode


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _normalize_expiry(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return None
    if len(text) == 10:
        try:
            return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def normalize_option_contract_row(row: dict[str, object]) -> dict[str, object]:
    symbol = _normalize_symbol(row.get("symbol"))
    expiry = _normalize_expiry(row.get("expiry"))
    right = str(row.get("right") or "").strip().upper()
    try:
        strike = float(row.get("strike") or 0.0)
    except (TypeError, ValueError):
        strike = 0.0
    try:
        bid = float(row.get("bid") or 0.0)
    except (TypeError, ValueError):
        bid = 0.0
    try:
        ask = float(row.get("ask") or 0.0)
    except (TypeError, ValueError):
        ask = 0.0
    normalized = {
        "symbol": symbol,
        "expiry": expiry,
        "strike": strike,
        "right": right,
        "bid": bid,
        "ask": ask,
    }
    for key in ("exchange", "currency", "local_symbol", "trading_class", "multiplier", "con_id", "last", "close"):
        if key in row:
            normalized[key] = row.get(key)
    return normalized


def _candidate_priority(row: dict[str, object], *, underlying_price: float | None) -> tuple[object, ...]:
    expiry = _normalize_expiry(row.get("expiry")) or "9999-12-31"
    try:
        strike = float(row.get("strike") or 0.0)
    except (TypeError, ValueError):
        strike = 0.0
    if underlying_price is None or underlying_price <= 0:
        return (expiry, strike)
    otm_penalty = 0 if strike > float(underlying_price) else 1
    distance = abs(strike - float(underlying_price))
    return (otm_penalty, expiry, distance, strike)


def fetch_option_candidates(
    session,
    *,
    mode: str,
    symbol: str,
    expiry: str | None = None,
    right: str = "C",
    timeout_seconds: float = 8.0,
    quote_limit: int | None = None,
    underlying_price: float | None = None,
) -> list[dict[str, object]]:
    if session is None:
        return []
    try:
        settings_row = get_or_create_ib_settings(session)
    except Exception:
        return []
    if resolve_ib_api_mode(settings_row) != "ib":
        return []
    host = str(getattr(settings_row, "host", "") or "").strip()
    try:
        port = int(getattr(settings_row, "port", 0) or 0)
    except (TypeError, ValueError):
        port = 0
    if not host or port <= 0:
        return []
    read_session = get_ib_read_session(mode=mode, host=host, port=port)
    if read_session is None:
        return []
    rows = read_session.fetch_option_contract_details(
        symbol=_normalize_symbol(symbol),
        expiry=expiry,
        right=right,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(rows, list):
        return []
    normalized_rows = [
        normalize_option_contract_row(row)
        for row in rows
        if isinstance(row, dict)
    ]
    if not normalized_rows:
        return []
    if underlying_price is not None:
        for row in normalized_rows:
            row["underlying_price"] = float(underlying_price)
    normalized_rows.sort(key=lambda item: _candidate_priority(item, underlying_price=underlying_price))
    quote_cap = len(normalized_rows)
    if quote_limit is not None:
        quote_cap = max(0, min(int(quote_limit), len(normalized_rows)))
    if quote_cap <= 0:
        return normalized_rows
    for index, row in enumerate(normalized_rows[:quote_cap]):
        snapshot = read_session.fetch_option_market_snapshot(
            symbol=str(row.get("symbol") or ""),
            expiry=str(row.get("expiry") or "").replace("-", ""),
            strike=float(row.get("strike") or 0.0),
            right=str(row.get("right") or "C"),
            timeout_seconds=max(2.0, min(float(timeout_seconds), 4.0)),
        )
        if isinstance(snapshot, dict):
            row.update(normalize_option_contract_row(snapshot))
            if underlying_price is not None:
                row["underlying_price"] = float(underlying_price)
        normalized_rows[index] = row
    return normalized_rows
