from __future__ import annotations

from typing import Any


def evaluate_orders(
    orders: list[dict[str, Any]],
    *,
    max_order_notional: float | None,
    max_position_ratio: float | None,
    portfolio_value: float | None,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    blocked: list[dict[str, Any]] = []
    reasons: list[str] = []
    for order in orders:
        qty = float(order.get("quantity") or 0)
        price = float(order.get("price") or 0)
        notional = qty * price
        if max_order_notional is not None and notional > float(max_order_notional):
            blocked.append(order)
            reasons.append(f"max_order_notional:{order.get('symbol')}")
            continue
        if max_position_ratio is not None and portfolio_value:
            ratio = notional / float(portfolio_value)
            if ratio > float(max_position_ratio):
                blocked.append(order)
                reasons.append(f"max_position_ratio:{order.get('symbol')}")
                continue
    ok = len(blocked) == 0
    return ok, blocked, reasons
