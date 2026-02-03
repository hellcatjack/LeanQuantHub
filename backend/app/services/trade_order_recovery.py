from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_

from app.models import TradeOrder, TradeRun, TradeSettings
from app.services.audit_log import record_audit
from app.services.ib_settings import get_or_create_ib_settings, resolve_ib_api_mode, _probe_ib_socket
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_quotes
from app.services.trade_guard import get_or_create_guard_state
from app.services.trade_orders import CLIENT_ORDER_ID_MAX_LEN, create_trade_order, update_trade_order_status


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_auto_recovery_config(session) -> dict[str, Any]:
    defaults = {
        "new_timeout_seconds": 45,
        "max_auto_retries": 1,
        "max_price_deviation_pct": 1.5,
        "allow_replace_outside_rth": False,
    }
    row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
    if row and isinstance(row.auto_recovery, dict):
        merged = dict(defaults)
        merged.update(row.auto_recovery)
        return merged
    return dict(defaults)


def _order_created_at(order: TradeOrder) -> datetime:
    if isinstance(order.created_at, datetime):
        return order.created_at
    if isinstance(order.updated_at, datetime):
        return order.updated_at
    return _utc_now()


def _normalize_symbol(value: str | None) -> str:
    return str(value or "").strip().upper()


def _extract_price(payload: dict | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("last", "close", "bid", "ask"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _fetch_latest_price(symbol: str) -> float | None:
    quotes = read_quotes(resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    target = _normalize_symbol(symbol)
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_symbol(item.get("symbol")) != target:
            continue
        payload = item.get("data") if isinstance(item.get("data"), dict) else item
        return _extract_price(payload)
    return None


def _quotes_stale() -> bool:
    quotes = read_quotes(resolve_bridge_root())
    return bool(quotes.get("stale", False))


def _build_replacement_client_order_id(base: str, attempt: int, suffix_extra: str | None = None) -> str:
    suffix = f"-r{attempt}"
    if suffix_extra:
        suffix = f"{suffix}-{suffix_extra}"
    max_base_len = CLIENT_ORDER_ID_MAX_LEN - len(suffix)
    trimmed = base[:max_base_len] if max_base_len > 0 else ""
    return f"{trimmed}{suffix}" if trimmed else suffix.lstrip("-")


def _ensure_unique_client_order_id(session, base: str, attempt: int, now: datetime) -> str:
    candidate = _build_replacement_client_order_id(base, attempt)
    exists = (
        session.query(TradeOrder.id)
        .filter(TradeOrder.client_order_id == candidate)
        .first()
    )
    if not exists:
        return candidate
    stamp = str(int(now.timestamp()))
    return _build_replacement_client_order_id(base, attempt, stamp)


def _merge_auto_meta(params: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    meta = dict(params.get("auto_recovery") or {})
    meta.update(updates)
    params["auto_recovery"] = meta
    return params


def _resolve_order_context(session, order: TradeOrder) -> tuple[int | None, str | None]:
    if order.run_id:
        run = session.get(TradeRun, order.run_id)
        if run:
            return run.project_id, (run.mode or "paper")
    params = order.params if isinstance(order.params, dict) else {}
    project_id = params.get("project_id")
    mode = params.get("mode") or "paper"
    try:
        project_id = int(project_id) if project_id is not None else None
    except (TypeError, ValueError):
        project_id = None
    return project_id, str(mode or "paper")


def _guard_allows(session, order: TradeOrder) -> bool:
    project_id, mode = _resolve_order_context(session, order)
    if project_id is None:
        return True
    state = get_or_create_guard_state(session, project_id=project_id, mode=mode)
    return state.status != "halted"


def _tws_reachable(session, *, timeout_seconds: float = 1.0) -> bool:
    settings = get_or_create_ib_settings(session)
    if resolve_ib_api_mode(settings) == "mock":
        return True
    return _probe_ib_socket(settings.host, settings.port, timeout_seconds=timeout_seconds)


def run_auto_recovery(session, *, now: datetime | None = None, limit: int = 200) -> dict[str, int]:
    clock = now or _utc_now()
    config = _resolve_auto_recovery_config(session)
    timeout_seconds = int(config.get("new_timeout_seconds") or 45)
    max_retries = int(config.get("max_auto_retries") or 1)
    max_deviation = float(config.get("max_price_deviation_pct") or 0.0)
    allow_outside_rth = bool(config.get("allow_replace_outside_rth"))

    cutoff = clock - timedelta(seconds=max(timeout_seconds, 0))
    orders = (
        session.query(TradeOrder)
        .filter(
            and_(
                TradeOrder.status == "NEW",
                TradeOrder.created_at <= cutoff,
                or_(TradeOrder.filled_quantity == None, TradeOrder.filled_quantity <= 0),
            )
        )
        .order_by(TradeOrder.created_at.asc())
        .limit(max(1, int(limit)))
        .all()
    )

    result = {"scanned": 0, "cancelled": 0, "replaced": 0, "skipped": 0, "failed": 0}
    if not orders:
        return result

    tws_ok = _tws_reachable(session)
    quotes_stale = _quotes_stale()

    for order in orders:
        result["scanned"] += 1
        params = dict(order.params or {})
        meta = dict(params.get("auto_recovery") or {})
        attempts = int(meta.get("attempts") or 0)
        if attempts >= max_retries:
            _merge_auto_meta(params, {"last_action": "stop", "last_reason": "max_retries", "last_at": clock.isoformat()})
            order.params = params
            session.commit()
            result["skipped"] += 1
            continue

        if not _guard_allows(session, order):
            _merge_auto_meta(params, {"last_action": "stop", "last_reason": "guard_halted", "last_at": clock.isoformat()})
            order.params = params
            session.commit()
            result["skipped"] += 1
            continue

        if not tws_ok:
            _merge_auto_meta(params, {"last_action": "stop", "last_reason": "tws_unreachable", "last_at": clock.isoformat()})
            order.params = params
            session.commit()
            result["skipped"] += 1
            continue

        try:
            update_trade_order_status(session, order, {"status": "CANCELED", "params": {"auto_recovery_cancel": True}})
            result["cancelled"] += 1
        except Exception:
            _merge_auto_meta(params, {"last_action": "cancel", "last_reason": "cancel_failed", "last_at": clock.isoformat()})
            order.params = params
            session.commit()
            result["failed"] += 1
            continue

        if not allow_outside_rth and quotes_stale:
            _merge_auto_meta(params, {"last_action": "cancel", "last_reason": "outside_rth", "last_at": clock.isoformat()})
            order.params = params
            session.commit()
            result["skipped"] += 1
            record_audit(
                session,
                action="trade_order.auto_recovery.cancel",
                resource_type="trade_order",
                resource_id=order.id,
                detail={"reason": "outside_rth"},
            )
            session.commit()
            continue

        replacement_params = dict(params)
        _merge_auto_meta(
            replacement_params,
            {
                "attempts": attempts + 1,
                "origin_order_id": order.id,
                "origin_client_order_id": order.client_order_id,
                "triggered_at": clock.isoformat(),
            },
        )

        if order.order_type == "LMT" and order.limit_price is not None and max_deviation > 0:
            latest_price = _fetch_latest_price(order.symbol)
            if latest_price is None:
                _merge_auto_meta(params, {"last_action": "cancel", "last_reason": "price_missing", "last_at": clock.isoformat()})
                order.params = params
                session.commit()
                result["skipped"] += 1
                continue
            deviation = abs(latest_price - float(order.limit_price)) / float(order.limit_price) * 100
            if deviation > max_deviation:
                _merge_auto_meta(params, {"last_action": "cancel", "last_reason": "price_deviation", "last_at": clock.isoformat()})
                order.params = params
                session.commit()
                result["skipped"] += 1
                continue

        client_order_id = _ensure_unique_client_order_id(session, order.client_order_id, attempts + 1, clock)
        payload = {
            "client_order_id": client_order_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": float(order.quantity),
            "order_type": order.order_type,
            "limit_price": order.limit_price,
            "params": replacement_params,
        }
        try:
            result_order = create_trade_order(session, payload, run_id=order.run_id)
            session.commit()
            session.refresh(result_order.order)
        except Exception:
            _merge_auto_meta(params, {"last_action": "replace", "last_reason": "replace_failed", "last_at": clock.isoformat()})
            order.params = params
            session.commit()
            result["failed"] += 1
            continue

        result["replaced"] += 1
        record_audit(
            session,
            action="trade_order.auto_recovery.replace",
            resource_type="trade_order",
            resource_id=result_order.order.id,
            detail={"origin_order_id": order.id, "attempt": attempts + 1},
        )
        session.commit()

    return result
