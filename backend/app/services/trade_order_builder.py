from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class OrderDraft:
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None


def build_orders(
    items: list[dict[str, Any]],
    *,
    price_map: dict[str, float],
    portfolio_value: float,
    cash_buffer_ratio: float = 0.0,
    lot_size: int = 1,
    order_type: str = "MKT",
    limit_price: float | None = None,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    normalized_order_type = str(order_type or "MKT").strip().upper()
    if normalized_order_type == "LMT" and limit_price is None:
        return []
    effective_value = portfolio_value * (1.0 - max(0.0, cash_buffer_ratio))
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        weight = item.get("weight")
        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            continue
        price = price_map.get(symbol)
        if price is None or price <= 0:
            continue
        side = "BUY" if weight_value >= 0 else "SELL"
        target = abs(weight_value) * effective_value
        raw_qty = target / price
        lot = max(1, int(lot_size))
        qty = int(raw_qty / lot + 0.5) * lot
        if qty <= 0:
            continue
        orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": qty,
                "order_type": normalized_order_type,
                "limit_price": limit_price,
            }
        )
    return orders
