from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func

from app.models import TradeOrder, TradeOrderClientIdSeq, TradeRun
from app.services.trade_run_progress import update_trade_run_progress


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"SUBMITTED", "CANCELED", "REJECTED"},
    "SUBMITTED": {"PARTIAL", "FILLED", "CANCELED", "REJECTED"},
    "PARTIAL": {"PARTIAL", "FILLED", "CANCELED"},
    "FILLED": set(),
    "CANCELED": set(),
    "REJECTED": set(),
}

CLIENT_ORDER_ID_MAX_LEN = 64


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


def get_client_order_id_seq(session) -> int:
    if session.bind and session.bind.dialect.name == "sqlite":
        next_id = session.query(func.max(TradeOrderClientIdSeq.id)).scalar() or 0
        seq_row = TradeOrderClientIdSeq(id=int(next_id) + 1)
        session.add(seq_row)
        session.flush()
    else:
        seq_row = TradeOrderClientIdSeq()
        session.add(seq_row)
        session.flush()
    if not seq_row.id:
        raise ValueError("client_order_id_seq_failed")
    return int(seq_row.id)


def _should_apply_manual_client_order_id(payload: dict[str, Any], run_id: int | None) -> bool:
    if run_id is not None:
        return False
    base_id = str(payload.get("client_order_id") or "").strip()
    if base_id.startswith("oi_"):
        return False
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if params.get("client_order_id_auto") is True:
        return False
    source = str(params.get("source") or "").strip()
    if source == "decision_snapshot":
        return False
    return True


def apply_manual_client_order_id(payload: dict[str, Any], *, seq_id: int) -> dict[str, Any]:
    base = str(payload.get("client_order_id") or "").strip()
    suffix = _base36(int(seq_id))
    suffix_token = f"-{suffix}"
    max_base_len = CLIENT_ORDER_ID_MAX_LEN - len(suffix_token)
    if max_base_len > 0:
        truncated = base if len(base) <= max_base_len else base[:max_base_len]
        client_order_id = f"{truncated}{suffix_token}" if truncated else suffix
    else:
        client_order_id = suffix
    params = dict(payload.get("params") or {})
    params.setdefault("original_client_order_id", base)
    updated = dict(payload)
    updated["client_order_id"] = client_order_id
    updated["params"] = params
    return updated


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
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    intent_only = params.get("intent_only") is True
    if quantity_value < 0:
        raise ValueError("quantity_invalid")
    if quantity_value == 0 and not intent_only:
        raise ValueError("quantity_invalid")
    if order_type == "LMT" and payload.get("limit_price") is None:
        raise ValueError("limit_price_required")


def create_trade_order(session, payload: dict[str, Any], run_id: int | None = None) -> OrderCreateResult:
    working_payload = dict(payload)
    if _should_apply_manual_client_order_id(working_payload, run_id):
        seq_id = get_client_order_id_seq(session)
        working_payload = apply_manual_client_order_id(working_payload, seq_id=seq_id)
    _validate_order_payload(working_payload)
    client_order_id = str(working_payload["client_order_id"]).strip()
    symbol = str(working_payload["symbol"]).strip().upper()
    side = _normalize_side(working_payload["side"])
    order_type = _normalize_order_type(working_payload.get("order_type") or "MKT")
    limit_price = working_payload.get("limit_price")
    quantity = float(working_payload["quantity"])
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
        params=working_payload.get("params"),
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
    if order.run_id:
        run = session.get(TradeRun, order.run_id)
        if run:
            stage = f"order_{target_status.lower()}"
            reason = f"{order.id}:{order.symbol}"
            update_trade_run_progress(session, run, stage, reason=reason, commit=True)
    return order
