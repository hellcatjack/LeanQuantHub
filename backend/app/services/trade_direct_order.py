from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models import TradeOrder
from app.services.audit_log import record_audit
from app.services.ib_settings import get_or_create_ib_settings, resolve_ib_api_mode
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_quotes
from app.services.trade_direct_intent import build_direct_intent_items
from app.services.trade_orders import create_trade_order
from app.services.trade_order_types import is_limit_like, normalize_order_type, validate_order_type
from app.services.ib_client_id_pool import (
    ClientIdPoolExhausted,
    attach_lease_pid,
    lease_client_id,
    select_worker_client_id,
)
from app.services.lean_execution import build_execution_config, launch_execution_async
from app.services.lean_bridge_watchdog import refresh_bridge
from app.schemas import TradeDirectOrderOut

_DIRECT_RETRY_BASE_SECONDS = 20
_DIRECT_RETRY_MAX_SECONDS = 300


_SESSION_EXTENDED = {
    "pre",
    "premarket",
    "pre_market",
    "post",
    "after",
    "afterhours",
    "after_hours",
    "night",
    "overnight",
}


def validate_direct_order_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in {"paper", "live"}:
        return False, "mode_invalid"

    symbol = str(payload.get("symbol") or "").strip()
    if not symbol:
        return False, "symbol_required"

    side = str(payload.get("side") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        return False, "side_invalid"

    try:
        order_type = validate_order_type(payload.get("order_type") or "MKT")
    except ValueError:
        return False, "order_type_invalid"

    if is_limit_like(order_type) and payload.get("limit_price") is not None:
        try:
            value = float(payload.get("limit_price"))
        except (TypeError, ValueError):
            return False, "limit_price_invalid"
        if value <= 0:
            return False, "limit_price_invalid"

    try:
        quantity = float(payload.get("quantity"))
    except (TypeError, ValueError):
        return False, "quantity_invalid"
    if quantity <= 0:
        return False, "quantity_invalid"

    if mode == "live":
        token = str(payload.get("live_confirm_token") or "").strip().upper()
        if token != "LIVE":
            return False, "live_confirm_required"

    return True, ""


def _select_worker(session, *, mode: str) -> int | None:
    return select_worker_client_id(session, mode=mode)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _compute_retry_delay(retry_count: int) -> int:
    if retry_count <= 1:
        return _DIRECT_RETRY_BASE_SECONDS
    delay = _DIRECT_RETRY_BASE_SECONDS * (2 ** (retry_count - 1))
    return int(min(delay, _DIRECT_RETRY_MAX_SECONDS))


def _update_retry_meta(order: TradeOrder, *, pending: bool, reason: str) -> dict:
    params = dict(order.params or {})
    meta = dict(params.get("direct_retry") or {})
    retry_count = int(meta.get("count") or 0) + 1
    now = _now_utc()
    delay = _compute_retry_delay(retry_count)
    next_at = now + timedelta(seconds=delay)
    meta.update(
        {
            "count": retry_count,
            "pending": pending,
            "last_reason": reason,
            "last_at": now.isoformat().replace("+00:00", "Z"),
            "next_retry_at": next_at.isoformat().replace("+00:00", "Z"),
        }
    )
    params["direct_retry"] = meta
    order.params = params
    return meta


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _normalize_session(value: object) -> str:
    text = str(value or "").strip().lower()
    return text


def _infer_outside_rth(params: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(params, dict):
        return False, ""
    session = _normalize_session(params.get("session") or params.get("execution_session") or params.get("trading_session"))
    explicit = params.get("allow_outside_rth")
    if explicit is None:
        explicit = params.get("outside_rth")
    if explicit is True:
        return True, session
    if explicit is False:
        return False, session
    if session in _SESSION_EXTENDED:
        return True, session
    return False, session


def _pick_quote_limit_price(item: dict[str, Any], *, side: str, prefer_mid: bool = False) -> float | None:
    if not isinstance(item, dict):
        return None
    last = item.get("last")
    bid = item.get("bid")
    ask = item.get("ask")
    try:
        last_value = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_value = None
    try:
        bid_value = float(bid) if bid is not None else None
    except (TypeError, ValueError):
        bid_value = None
    try:
        ask_value = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        ask_value = None

    if prefer_mid and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0

    # Prefer last trade if available. Otherwise prefer a reasonable point for the side.
    if last_value is not None and last_value > 0:
        return last_value

    if (not prefer_mid) and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0
    normalized_side = str(side or "").strip().upper()
    if normalized_side == "BUY":
        if ask_value is not None and ask_value > 0:
            return ask_value
        if bid_value is not None and bid_value > 0:
            return bid_value
    if normalized_side == "SELL":
        if bid_value is not None and bid_value > 0:
            return bid_value
        if ask_value is not None and ask_value > 0:
            return ask_value
    if bid_value is not None and bid_value > 0:
        return bid_value
    if ask_value is not None and ask_value > 0:
        return ask_value
    return None


def _resolve_limit_price_from_bridge(*, symbol: str, side: str, prefer_mid: bool = False) -> float | None:
    symbol_key = _normalize_symbol(symbol)
    if not symbol_key:
        return None
    quotes = read_quotes(resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_symbol(item.get("symbol")) != symbol_key:
            continue
        price = _pick_quote_limit_price(item, side=side, prefer_mid=prefer_mid)
        if price is not None and price > 0:
            return float(price)
    return None


def _ensure_direct_intent(order: TradeOrder) -> Path:
    intent_dir = Path(settings.artifact_root) / "order_intents"
    intent_dir.mkdir(parents=True, exist_ok=True)
    intent_path = intent_dir / f"order_intent_direct_{order.id}.json"
    params = dict(order.params or {})
    allow_outside_rth, session = _infer_outside_rth(params)
    intent_items = build_direct_intent_items(
        order_id=order.id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        order_type=order.order_type or "MKT",
        limit_price=order.limit_price,
        allow_outside_rth=allow_outside_rth,
        session=session or None,
    )
    intent_path.write_text(
        json.dumps(intent_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return intent_path


def _launch_direct_execution(
    session,
    *,
    order: TradeOrder,
    mode: str,
    project_id: int,
    intent_path: str,
    output_dir: Path,
) -> TradeDirectOrderOut:
    lease = None
    client_id = _select_worker(session, mode=mode)
    if client_id is None:
        try:
            lease = lease_client_id(session, order_id=order.id, mode=mode, output_dir=str(output_dir))
            client_id = lease.client_id
        except ClientIdPoolExhausted:
            _update_retry_meta(order, pending=True, reason="client_id_busy")
            session.commit()
            return TradeDirectOrderOut(
                order_id=order.id,
                status=order.status or "NEW",
                execution_status="retry_pending",
                intent_path=intent_path,
            )

    config = build_execution_config(
        intent_path=intent_path,
        brokerage="InteractiveBrokersBrokerage",
        project_id=project_id,
        mode=mode,
        client_id=client_id,
        lean_bridge_output_dir=str(output_dir),
    )
    exec_dir = Path(settings.artifact_root) / "lean_execution"
    exec_dir.mkdir(parents=True, exist_ok=True)
    config_path = exec_dir / f"direct_order_{order.id}_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        pid = launch_execution_async(config_path=str(config_path))
    except Exception:
        _update_retry_meta(order, pending=True, reason="launch_failed")
        session.commit()
        return TradeDirectOrderOut(
            order_id=order.id,
            status=order.status or "NEW",
            execution_status="retry_pending",
            intent_path=intent_path,
            config_path=str(config_path),
        )
    if pid <= 0:
        _update_retry_meta(order, pending=True, reason="launch_failed")
        session.commit()
        return TradeDirectOrderOut(
            order_id=order.id,
            status=order.status or "NEW",
            execution_status="retry_pending",
            intent_path=intent_path,
            config_path=str(config_path),
        )

    if lease is not None:
        attach_lease_pid(session, lease_token=lease.lease_token or "", pid=pid)

    probe_path = exec_dir / f"direct_order_{order.id}.json"
    probe_path.write_text(
        json.dumps(
            {
                "order_id": order.id,
                "mode": mode,
                "intent_path": intent_path,
                "config_path": str(config_path),
                "submitted_at": datetime.utcnow().isoformat() + "Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _update_retry_meta(order, pending=False, reason="submitted")
    session.commit()

    bridge_status = refresh_bridge(session, mode=mode, reason="order_submit", force=False)
    refresh_result = bridge_status.get("last_refresh_result")

    return TradeDirectOrderOut(
        order_id=order.id,
        status=order.status or "NEW",
        execution_status="submitted_lean",
        intent_path=intent_path,
        config_path=str(config_path),
        bridge_status=bridge_status,
        refresh_result=refresh_result if isinstance(refresh_result, str) else None,
    )


def retry_direct_order(session, *, order_id: int, reason: str | None = None, force: bool = False) -> TradeDirectOrderOut:
    order = session.get(TradeOrder, order_id)
    if order is None:
        raise ValueError("order_not_found")
    status = str(order.status or "").strip().upper()
    if not force and status not in {"NEW", "REJECTED"}:
        raise ValueError("order_not_retryable")
    params = dict(order.params or {})
    mode = str(params.get("mode") or "paper").strip().lower() or "paper"
    project_id = int(params.get("project_id") or 0)
    intent_path = str(_ensure_direct_intent(order))
    output_dir = Path(settings.data_root or "/data/share/stock/data") / "lean_bridge" / f"direct_{order.id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return _launch_direct_execution(
        session,
        order=order,
        mode=mode,
        project_id=project_id,
        intent_path=intent_path,
        output_dir=output_dir,
    )


def submit_direct_order(session, payload: dict[str, Any]) -> TradeDirectOrderOut:
    ok, reason = validate_direct_order_payload(payload)
    if not ok:
        raise ValueError(reason)

    project_id = int(payload.get("project_id") or 0)
    mode = str(payload.get("mode") or "paper").strip().lower() or "paper"

    settings_row = get_or_create_ib_settings(session)
    api_mode = resolve_ib_api_mode(settings_row)
    if api_mode != "ib":
        raise ValueError("ib_api_mode_disabled")
    if not settings_row.host or not settings_row.port:
        raise ValueError("ib_settings_missing")

    params = dict(payload.get("params") or {})
    params.setdefault("source", "direct")
    params.setdefault("mode", mode)
    params.setdefault("project_id", project_id)

    order_type = validate_order_type(payload.get("order_type") or "MKT")
    limit_price = payload.get("limit_price")
    if is_limit_like(order_type) and limit_price is None:
        picked = _resolve_limit_price_from_bridge(
            symbol=str(payload.get("symbol") or ""),
            side=str(payload.get("side") or ""),
            prefer_mid=order_type == "PEG_MID",
        )
        if picked is None:
            raise ValueError("limit_price_unavailable")
        limit_price = float(picked)

    order_payload = {
        "client_order_id": payload.get("client_order_id"),
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "quantity": payload.get("quantity"),
        "order_type": order_type,
        "limit_price": limit_price,
        "params": params,
    }

    result = create_trade_order(session, order_payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    intent_path = _ensure_direct_intent(order)
    output_dir = Path(settings.data_root or "/data/share/stock/data") / "lean_bridge" / f"direct_{order.id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = _launch_direct_execution(
        session,
        order=order,
        mode=mode,
        project_id=project_id,
        intent_path=str(intent_path),
        output_dir=output_dir,
    )

    record_audit(
        session,
        action="trade_order.direct_submit",
        resource_type="trade_order",
        resource_id=order.id,
        detail={
            "mode": mode,
            "intent_path": str(intent_path),
            "execution_status": result.execution_status,
        },
    )
    session.commit()

    return result
