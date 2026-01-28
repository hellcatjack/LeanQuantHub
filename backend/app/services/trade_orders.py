from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models import TradeOrder


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"SUBMITTED", "CANCELED", "REJECTED"},
    "SUBMITTED": {"PARTIAL", "FILLED", "CANCELED", "REJECTED"},
    "PARTIAL": {"PARTIAL", "FILLED", "CANCELED"},
    "FILLED": set(),
    "CANCELED": set(),
    "REJECTED": set(),
}


@dataclass
class OrderCreateResult:
    order: TradeOrder
    created: bool


def _normalize_status(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_side(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_order_type(value: str) -> str:
    return str(value or "").strip().upper()


def _base36(value: int) -> str:
    if value < 0:
        raise ValueError("base36_negative")
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    result = []
    num = value
    while num > 0:
        num, rem = divmod(num, 36)
        result.append(digits[rem])
    return "".join(reversed(result))


def build_manual_client_order_id(base: str, seq_id: int) -> str:
    suffix = _base36(int(seq_id))
    return f"{base}-{suffix}"


def validate_transition(current: str, target: str) -> None:
    if current == target:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"invalid_transition:{current}->{target}")


def _validate_order_payload(payload: dict[str, Any]) -> None:
    if not payload.get("client_order_id"):
        raise ValueError("client_order_id_required")
    if not payload.get("symbol"):
        raise ValueError("symbol_required")
    side = _normalize_side(payload.get("side"))
    if side not in {"BUY", "SELL"}:
        raise ValueError("side_invalid")
    order_type = _normalize_order_type(payload.get("order_type") or "MKT")
    if order_type not in {"MKT", "LMT"}:
        raise ValueError("order_type_invalid")
    quantity = payload.get("quantity")
    try:
        quantity_value = float(quantity)
    except (TypeError, ValueError):
        raise ValueError("quantity_invalid") from None
    if quantity_value <= 0:
        raise ValueError("quantity_invalid")
    if order_type == "LMT" and payload.get("limit_price") is None:
        raise ValueError("limit_price_required")


def create_trade_order(session, payload: dict[str, Any], run_id: int | None = None) -> OrderCreateResult:
    _validate_order_payload(payload)
    client_order_id = str(payload["client_order_id"]).strip()
    symbol = str(payload["symbol"]).strip().upper()
    side = _normalize_side(payload["side"])
    order_type = _normalize_order_type(payload.get("order_type") or "MKT")
    limit_price = payload.get("limit_price")
    quantity = float(payload["quantity"])
    for pending in session.new:
        if isinstance(pending, TradeOrder) and pending.client_order_id == client_order_id:
            mismatch = (
                pending.symbol != symbol
                or pending.side != side
                or pending.quantity != quantity
                or pending.order_type != order_type
                or (pending.limit_price or None) != (limit_price or None)
            )
            if mismatch:
                raise ValueError("client_order_id_conflict")
            return OrderCreateResult(order=pending, created=False)
    existing = (
        session.query(TradeOrder)
        .filter(TradeOrder.client_order_id == client_order_id)
        .one_or_none()
    )
    if existing:
        mismatch = (
            existing.symbol != symbol
            or existing.side != side
            or existing.quantity != quantity
            or existing.order_type != order_type
            or (existing.limit_price or None) != (limit_price or None)
        )
        if mismatch:
            raise ValueError("client_order_id_conflict")
        return OrderCreateResult(order=existing, created=False)
    order = TradeOrder(
        run_id=run_id,
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        status="NEW",
        params=payload.get("params"),
    )
    session.add(order)
    return OrderCreateResult(order=order, created=True)


def update_trade_order_status(session, order: TradeOrder, payload: dict[str, Any]) -> TradeOrder:
    target_status = _normalize_status(payload.get("status"))
    if not target_status:
        raise ValueError("status_required")
    current_status = _normalize_status(order.status)
    validate_transition(current_status, target_status)
    order.status = target_status
    if payload.get("filled_quantity") is not None:
        order.filled_quantity = float(payload["filled_quantity"])
    if payload.get("avg_fill_price") is not None:
        order.avg_fill_price = float(payload["avg_fill_price"])
    if payload.get("params"):
        merged = dict(order.params or {})
        merged.update(payload.get("params") or {})
        order.params = merged
    order.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(order)
    return order
