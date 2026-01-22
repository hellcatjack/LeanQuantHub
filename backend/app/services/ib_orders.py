from __future__ import annotations

from datetime import datetime
from datetime import timedelta

try:
    from ibapi.order import Order as IBOrder
except Exception:  # pragma: no cover - optional dependency
    IBOrder = None  # type: ignore[assignment]

from app.models import TradeFill, TradeOrder
from app.services.ib_market import _build_contract, ib_adapter
from app.services.ib_settings import get_or_create_ib_settings
from app.services.trade_orders import update_trade_order_status


def apply_fill_to_order(
    session,
    order: TradeOrder,
    *,
    fill_qty: float,
    fill_price: float,
    fill_time: datetime,
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
    return {"filled": filled, "rejected": rejected}


def _parse_ib_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) >= 17 and text[8] == " ":
            return datetime.strptime(text[:17], "%Y%m%d %H:%M:%S")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _build_ib_order(order: TradeOrder) -> IBOrder:
    if IBOrder is None:
        raise RuntimeError("ibapi_not_available")
    ib_order = IBOrder()
    ib_order.action = str(order.side or "").strip().upper()
    ib_order.orderType = str(order.order_type or "MKT").strip().upper()
    ib_order.totalQuantity = float(order.quantity)
    if ib_order.orderType == "LMT":
        if order.limit_price is None:
            raise ValueError("limit_price_required")
        ib_order.lmtPrice = float(order.limit_price)
    return ib_order


def submit_orders_live(session, orders, *, price_map: dict[str, float]):
    settings_row = get_or_create_ib_settings(session)
    filled = 0
    rejected = 0
    results: list[dict[str, object]] = []
    with ib_adapter(settings_row) as api:
        for order in orders:
            try:
                contract = _build_contract(order.symbol)
                ib_order = _build_ib_order(order)
            except Exception as exc:
                rejected += 1
                update_trade_order_status(
                    session,
                    order,
                    {"status": "REJECTED", "params": {"reason": str(exc)}},
                )
                results.append({"id": order.id, "status": "rejected", "error": str(exc)})
                continue

            payload, error = api.place_order(contract, ib_order, timeout=5.0)
            if error:
                rejected += 1
                update_trade_order_status(
                    session,
                    order,
                    {"status": "REJECTED", "params": {"reason": error}},
                )
                results.append({"id": order.id, "status": "rejected", "error": error})
                continue

            broker_order_id = payload.get("order_id") if payload else None
            if broker_order_id is not None:
                update_trade_order_status(
                    session,
                    order,
                    {"status": order.status or "NEW", "params": {"broker_order_id": broker_order_id}},
                )

            status = str(payload.get("status") or "").strip().upper()
            fills = list(payload.get("fills") or [])
            commission = payload.get("commission")

            last_fill = None
            if fills:
                for fill in fills:
                    fill_time = _parse_ib_time(fill.get("time")) or datetime.utcnow()
                    last_fill = apply_fill_to_order(
                        session,
                        order,
                        fill_qty=float(fill.get("quantity") or 0),
                        fill_price=float(fill.get("price") or 0),
                        fill_time=fill_time,
                    )
            elif float(payload.get("filled") or 0) > 0:
                fill_price = float(payload.get("avg_fill_price") or 0) or float(price_map.get(order.symbol) or 0)
                fill_time = datetime.utcnow()
                last_fill = apply_fill_to_order(
                    session,
                    order,
                    fill_qty=float(payload.get("filled") or 0),
                    fill_price=fill_price,
                    fill_time=fill_time,
                )
            elif status in {"SUBMITTED", "PRE_SUBMITTED"}:
                update_trade_order_status(session, order, {"status": "SUBMITTED"})
            elif status in {"CANCELLED", "CANCELED", "APICANCELLED"}:
                update_trade_order_status(session, order, {"status": "CANCELED"})
            elif status == "REJECTED":
                update_trade_order_status(session, order, {"status": "REJECTED"})

            if last_fill is not None and commission is not None:
                last_fill.commission = float(commission)
                session.commit()
                session.refresh(last_fill)

            session.refresh(order)
            if order.status == "FILLED":
                filled += 1
                results.append({"id": order.id, "status": "filled"})
            elif order.status in {"REJECTED", "CANCELED"}:
                rejected += 1
                results.append({"id": order.id, "status": "rejected"})
            else:
                results.append({"id": order.id, "status": "submitted"})

    overall = "filled"
    if rejected and filled:
        overall = "partial"
    elif rejected and not filled:
        overall = "rejected"
    return {"status": overall, "filled": filled, "rejected": rejected, "orders": results}
