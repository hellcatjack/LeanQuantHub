from __future__ import annotations

import math
from typing import Any


def _coerce_float(raw: object, *, default: float | None = 0.0) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return value


def _coerce_non_negative_float(raw: object, *, default: float = 0.0) -> float:
    value = _coerce_float(raw, default=default)
    if value is None:
        return max(0.0, float(default))
    return max(0.0, value)


def _normalize_lot_and_min_qty(*, lot_size: int, min_qty: int) -> tuple[int, int]:
    lot = max(1, int(lot_size or 1))
    min_qty_value = max(1, int(min_qty or 1))
    if min_qty_value % lot != 0:
        min_qty_value = int(math.ceil(min_qty_value / lot)) * lot
    return lot, min_qty_value


def _estimate_price(
    order: dict[str, Any],
    *,
    price_map: dict[str, float],
    limit_price_map: dict[str, float] | None,
) -> float | None:
    symbol = str(order.get("symbol") or "").strip().upper()
    for raw in (
        order.get("limit_price"),
        (limit_price_map or {}).get(symbol),
        price_map.get(symbol),
    ):
        value = _coerce_float(raw, default=None)
        if value is not None and value > 0:
            return value
    return None


def _estimated_buy_cost(
    quantity: float,
    price: float,
    *,
    fee_bps: float,
    price_buffer_bps: float,
) -> float:
    buffered_price = float(price) * (1.0 + max(0.0, float(price_buffer_bps or 0.0)) / 10_000.0)
    return float(quantity) * buffered_price * (1.0 + max(0.0, float(fee_bps or 0.0)) / 10_000.0)


def _budget_from_cash(
    *,
    cash_available: float,
    portfolio_value: float | None,
    cash_buffer_ratio: float,
) -> tuple[float, float]:
    reserve = 0.0
    if portfolio_value is not None and portfolio_value > 0:
        reserve = portfolio_value * min(max(float(cash_buffer_ratio or 0.0), 0.0), 1.0)
    return max(0.0, float(cash_available) - reserve), reserve


def apply_cash_budget_to_order_drafts(
    orders: list[dict[str, Any]],
    *,
    price_map: dict[str, float],
    cash_available: float | None,
    portfolio_value: float | None,
    cash_buffer_ratio: float,
    lot_size: int,
    min_qty: int,
    fee_bps: float,
    price_buffer_bps: float,
    limit_price_map: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Trim BUY drafts so unconfirmed sell proceeds are never reused as cash.

    SELL drafts are preserved. BUY drafts consume a single cash budget in order.
    If a BUY cannot fit the remaining budget, it is reduced to the largest whole
    lot that fits; if that falls below min_qty, the BUY is skipped.
    """

    original_orders = [dict(order) for order in orders]
    cash_value = _coerce_float(cash_available, default=None)
    if cash_value is None:
        return original_orders, {
            "applied": False,
            "reason": "missing_cash_available",
            "adjustments": [],
            "blocked_no_orders": False,
        }

    portfolio_value_float = _coerce_float(portfolio_value, default=None)
    budget, cash_reserve = _budget_from_cash(
        cash_available=cash_value,
        portfolio_value=portfolio_value_float,
        cash_buffer_ratio=cash_buffer_ratio,
    )
    lot, min_qty_value = _normalize_lot_and_min_qty(lot_size=lot_size, min_qty=min_qty)
    fee = _coerce_non_negative_float(fee_bps, default=0.0)
    price_buffer = _coerce_non_negative_float(price_buffer_bps, default=0.0)

    adjusted: list[dict[str, Any]] = []
    adjustments: list[dict[str, Any]] = []
    estimated_before = 0.0
    estimated_after = 0.0
    remaining = budget
    buy_seen = False

    for order in original_orders:
        side = str(order.get("side") or "").strip().upper()
        if side != "BUY":
            adjusted.append(order)
            continue

        buy_seen = True
        symbol = str(order.get("symbol") or "").strip().upper()
        requested_qty = _coerce_non_negative_float(order.get("quantity"), default=0.0)
        if requested_qty <= 0:
            continue
        price = _estimate_price(order, price_map=price_map, limit_price_map=limit_price_map)
        if price is None:
            adjustments.append(
                {
                    "symbol": symbol,
                    "side": "BUY",
                    "action": "skipped",
                    "requested_quantity": requested_qty,
                    "approved_quantity": 0.0,
                    "estimated_price": None,
                    "estimated_cost_before": 0.0,
                    "estimated_cost_after": 0.0,
                }
            )
            continue

        requested_cost = _estimated_buy_cost(
            requested_qty,
            price,
            fee_bps=fee,
            price_buffer_bps=price_buffer,
        )
        estimated_before += requested_cost
        if requested_cost <= remaining + 1e-9:
            adjusted.append(order)
            estimated_after += requested_cost
            remaining = max(0.0, remaining - requested_cost)
            continue

        cost_per_share = _estimated_buy_cost(
            1.0,
            price,
            fee_bps=fee,
            price_buffer_bps=price_buffer,
        )
        affordable_lots = (
            int(math.floor((remaining / cost_per_share + 1e-9) / float(lot)))
            if cost_per_share > 0
            else 0
        )
        approved_qty = float(affordable_lots * lot)
        if approved_qty < float(min_qty_value):
            adjustments.append(
                {
                    "symbol": symbol,
                    "side": "BUY",
                    "action": "skipped",
                    "requested_quantity": requested_qty,
                    "approved_quantity": 0.0,
                    "estimated_price": price,
                    "estimated_cost_before": requested_cost,
                    "estimated_cost_after": 0.0,
                }
            )
            continue

        approved_cost = _estimated_buy_cost(
            approved_qty,
            price,
            fee_bps=fee,
            price_buffer_bps=price_buffer,
        )
        reduced = dict(order)
        reduced["quantity"] = approved_qty
        adjusted.append(reduced)
        adjustments.append(
            {
                "symbol": symbol,
                "side": "BUY",
                "action": "reduced",
                "requested_quantity": requested_qty,
                "approved_quantity": approved_qty,
                "estimated_price": price,
                "estimated_cost_before": requested_cost,
                "estimated_cost_after": approved_cost,
            }
        )
        estimated_after += approved_cost
        remaining = max(0.0, remaining - approved_cost)

    meta = {
        "applied": True,
        "reason": "cash_budget",
        "cash_available": cash_value,
        "cash_reserve": cash_reserve,
        "cash_budget": budget,
        "remaining_budget": remaining,
        "fee_bps": fee,
        "price_buffer_bps": price_buffer,
        "estimated_buy_cost_before": estimated_before,
        "estimated_buy_cost_after": estimated_after,
        "adjustments": adjustments,
        "blocked_no_orders": bool(buy_seen and original_orders and not adjusted),
    }
    return adjusted, meta
