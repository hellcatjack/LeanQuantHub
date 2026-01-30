from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_

from app.models import AuditLog, TradeFill, TradeOrder
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_bridge_status, read_quotes
from app.services.lean_bridge_watchlist import refresh_leader_watchlist
from app.services.ib_settings import get_or_create_ib_settings, get_or_create_ib_state

_SNAPSHOT_FRESH_SECONDS = 300


def _mask_account(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def _read_connection(session) -> dict[str, Any]:
    state = get_or_create_ib_state(session)
    return {
        "status": state.status or "unknown",
        "message": state.message,
        "last_heartbeat": state.last_heartbeat,
        "updated_at": state.updated_at,
    }


def _read_config(session) -> dict[str, Any]:
    settings = get_or_create_ib_settings(session)
    return {
        "host": settings.host,
        "port": settings.port,
        "client_id": settings.client_id,
        "account_id": _mask_account(settings.account_id),
        "mode": settings.mode,
        "market_data_type": settings.market_data_type,
        "api_mode": settings.api_mode,
        "use_regulatory_snapshot": bool(settings.use_regulatory_snapshot),
    }


def _read_stream_status() -> dict[str, Any]:
    status = read_bridge_status(_resolve_bridge_root())
    subscribed = status.get("subscribed_symbols") or status.get("symbols") or []
    return {
        "status": status.get("status") or "unknown",
        "subscribed_count": len(subscribed),
        "last_heartbeat": status.get("last_heartbeat"),
        "ib_error_count": int(status.get("error_count") or status.get("ib_error_count") or 0),
        "last_error": status.get("last_error"),
        "market_data_type": status.get("market_data_type") or "unknown",
    }


def _read_snapshot_cache() -> dict[str, Any]:
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    updated_at = quotes.get("updated_at") or quotes.get("refreshed_at")
    last_snapshot_at = _parse_timestamp(updated_at)
    status = "unknown"
    if last_snapshot_at:
        if datetime.utcnow() - last_snapshot_at <= timedelta(seconds=_SNAPSHOT_FRESH_SECONDS):
            status = "fresh"
        else:
            status = "stale"
    return {
        "status": status,
        "last_snapshot_at": last_snapshot_at,
        "symbol_sample_count": len(items),
    }


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _read_orders(session) -> dict[str, Any]:
    latest_order = (
        session.query(TradeOrder)
        .order_by(TradeOrder.created_at.desc())
        .first()
    )
    latest_fill = (
        session.query(TradeFill)
        .order_by(TradeFill.created_at.desc())
        .first()
    )
    return {
        "latest_order_id": latest_order.id if latest_order else None,
        "latest_order_status": latest_order.status if latest_order else None,
        "latest_order_at": latest_order.created_at if latest_order else None,
        "latest_fill_id": latest_fill.id if latest_fill else None,
        "latest_fill_at": latest_fill.created_at if latest_fill else None,
    }


def _read_alerts(session) -> dict[str, Any]:
    latest = (
        session.query(AuditLog)
        .filter(
            or_(
                AuditLog.action.like("ib.%"),
                AuditLog.action.like("trade.%"),
            )
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    return {
        "latest_alert_id": latest.id if latest else None,
        "latest_alert_at": latest.created_at if latest else None,
        "latest_alert_title": latest.action if latest else None,
    }


def _read_section(name: str, fn, errors: list[str], partial: dict[str, bool]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        partial["value"] = True
        errors.append(name)
        return {}


def build_ib_status_overview(session) -> dict[str, Any]:
    try:
        refresh_leader_watchlist(session, max_symbols=200)
    except Exception:
        pass
    errors: list[str] = []
    partial = {"value": False}
    connection = _read_section("connection", lambda: _read_connection(session), errors, partial)
    config = _read_section("config", lambda: _read_config(session), errors, partial)
    stream = _read_section("stream", _read_stream_status, errors, partial)
    snapshot_cache = _read_section("snapshot_cache", _read_snapshot_cache, errors, partial)
    orders = _read_section("orders", lambda: _read_orders(session), errors, partial)
    alerts = _read_section("alerts", lambda: _read_alerts(session), errors, partial)
    return {
        "connection": connection,
        "config": config,
        "stream": stream,
        "snapshot_cache": snapshot_cache,
        "orders": orders,
        "alerts": alerts,
        "partial": bool(partial["value"]),
        "errors": errors,
        "refreshed_at": datetime.utcnow(),
    }
