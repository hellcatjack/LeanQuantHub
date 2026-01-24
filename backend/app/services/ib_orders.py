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
    fill_time: datetime,
    exec_id: str | None = None,
) -> TradeFill:
    current_status = str(order.status or "").strip().upper()
    total_prev = float(order.filled_quantity or 0.0)
    total_new = total_prev + float(fill_qty)
    avg_prev = float(order.avg_fill_price or 0.0)
    avg_new = (avg_prev * total_prev + float(fill_price) * float(fill_qty)) / total_new

    target_status = "PARTIAL" if total_new < float(order.quantity) else "FILLED"
    if current_status == "NEW":
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
    update_trade_order_status(
        session,
        order,
        {"status": target_status, "filled_quantity": total_new, "avg_fill_price": avg_new},
    )
    fill = TradeFill(
        order_id=order.id,
        fill_quantity=float(fill_qty),
        fill_price=float(fill_price),
        commission=None,
        fill_time=fill_time,
        exec_id=exec_id,
        params={"source": "ib"},
    )
    session.add(fill)
    session.commit()
    session.refresh(order)
    return fill


def submit_orders_mock(session, orders, *, price_map: dict[str, float]):
    filled = 0
    rejected = 0
    for order in orders:
        price = price_map.get(order.symbol)
        if price is None:
            rejected += 1
            update_trade_order_status(session, order, {"status": "REJECTED", "params": {"reason": "price_unavailable"}})
            continue
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
        apply_fill_to_order(session, order, fill_qty=order.quantity, fill_price=price, fill_time=datetime.utcnow())
        filled += 1
    return {"filled": filled, "rejected": rejected, "cancelled": 0, "events": []}
