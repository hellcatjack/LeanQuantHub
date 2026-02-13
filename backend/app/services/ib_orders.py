from __future__ import annotations

from datetime import datetime

from app.models import TradeFill, TradeOrder
from app.services.trade_orders import update_trade_order_status


def apply_fill_to_order(
    session,
    order: TradeOrder,
    *,
    fill_qty: float,
    fill_price: float,
    fill_time: datetime | None = None,
    exec_id: str | None = None,
    commission: float | None = None,
    currency: str | None = None,
    exchange: str | None = None,
    params: dict | None = None,
) -> TradeFill:
    if fill_time is None:
        fill_time = datetime.utcnow()
    fill_qty_value = abs(float(fill_qty or 0.0))
    if fill_qty_value <= 0:
        raise ValueError("fill_qty_invalid")
    fill_price_value = float(fill_price or 0.0)
    if exec_id:
        existing = (
            session.query(TradeFill)
            .filter(TradeFill.order_id == order.id, TradeFill.exec_id == exec_id)
            .first()
        )
        if existing:
            return existing
    current_status = str(order.status or "").strip().upper()
    total_prev = float(order.filled_quantity or 0.0)
    total_new = total_prev + fill_qty_value
    avg_prev = float(order.avg_fill_price or 0.0)
    if total_new <= 0:
        total_prev = 0.0
        total_new = fill_qty_value
        avg_prev = 0.0
    avg_new = (avg_prev * total_prev + fill_price_value * fill_qty_value) / total_new
    target_status = "PARTIAL" if total_new < float(abs(order.quantity or 0.0)) else "FILLED"
    if current_status == "NEW":
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
    update_trade_order_status(
        session,
        order,
        {"status": target_status, "filled_quantity": total_new, "avg_fill_price": avg_new},
    )
    if not exec_id:
        exec_id = f"fill:{order.id}:{int(fill_time.timestamp() * 1000)}"
    fill = TradeFill(
        order_id=order.id,
        exec_id=exec_id,
        fill_quantity=fill_qty_value,
        fill_price=fill_price_value,
        commission=commission,
        fill_time=fill_time,
        currency=currency,
        exchange=exchange,
        params=params,
    )
    session.add(fill)
    session.commit()
    session.refresh(order)
    return fill
