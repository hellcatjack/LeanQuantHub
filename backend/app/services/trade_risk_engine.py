from __future__ import annotations

from typing import Any


def evaluate_orders(
    orders: list[dict[str, Any]],
    *,
    max_order_notional: float | None,
    max_position_ratio: float | None,
    portfolio_value: float | None,
    max_total_notional: float | None,
    max_symbols: int | None,
    cash_available: float | None,
    min_cash_buffer_ratio: float | None,
    enforce_cash_budget: bool = False,
    cash_buffer_ratio: float | None = None,
    buy_cost_buffer_bps: float | None = None,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    blocked: list[dict[str, Any]] = []
    reasons: list[str] = []
    if max_symbols is not None and len(orders) > int(max_symbols):
        reasons.append("max_symbols")
        return False, orders, reasons

    total_notional = 0.0
    for order in orders:
        qty = float(order.get("quantity") or 0)
        price = float(order.get("price") or 0)
        notional = qty * price
        total_notional += notional
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
    if max_total_notional is not None and total_notional > float(max_total_notional):
        reasons.append("max_total_notional")
        return False, orders, reasons
    if enforce_cash_budget:
        if cash_available is None:
            reasons.append("cash_budget:missing_cash_available")
            return False, orders, reasons
        cash_budget = float(cash_available)
        if cash_buffer_ratio is not None and portfolio_value is not None:
            cash_budget -= float(portfolio_value) * max(0.0, float(cash_buffer_ratio))
        cash_budget = max(0.0, cash_budget)
        cost_buffer = max(0.0, float(buy_cost_buffer_bps or 0.0)) / 10_000.0
        buy_cost = 0.0
        buy_orders: list[dict[str, Any]] = []
        for order in orders:
            if str(order.get("side") or "").strip().upper() != "BUY":
                continue
            qty = float(order.get("quantity") or 0)
            if qty <= 0:
                continue
            price = float(order.get("price") or 0)
            if price <= 0:
                reasons.append(f"cash_budget:missing_price:{order.get('symbol')}")
                return False, [order], reasons
            buy_orders.append(order)
            buy_cost += qty * price * (1.0 + cost_buffer)
        if buy_cost > cash_budget + 1e-9:
            reasons.append("cash_budget")
            return False, buy_orders, reasons
    if min_cash_buffer_ratio is not None and portfolio_value is not None:
        if cash_available is None:
            reasons.append("min_cash_buffer_ratio:missing_cash_available")
            return False, orders, reasons
        buffer_ratio = float(cash_available) / float(portfolio_value)
        if buffer_ratio < float(min_cash_buffer_ratio):
            reasons.append("min_cash_buffer_ratio")
            return False, orders, reasons
    ok = len(blocked) == 0
    return ok, blocked, reasons
