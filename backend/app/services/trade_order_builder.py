from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math

from app.services.trade_order_types import is_limit_like, validate_order_type


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
    min_qty: int = 1,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    normalized_order_type = str(order_type or "MKT").strip().upper()
    if normalized_order_type in {"LMT", "PEG_MID"} and limit_price is None:
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
        # Skip zero-weight items to avoid generating min-qty dust orders.
        if abs(weight_value) <= 1e-12:
            continue
        price = price_map.get(symbol)
        if price is None or price <= 0:
            continue
        side = "BUY" if weight_value >= 0 else "SELL"
        target = abs(weight_value) * effective_value
        raw_qty = target / price
        lot = max(1, int(lot_size))
        min_qty_value = max(1, int(min_qty))
        if min_qty_value % lot != 0:
            min_qty_value = int(math.ceil(min_qty_value / lot)) * lot
        qty = int(math.ceil(raw_qty / lot)) * lot
        if qty < min_qty_value:
            qty = min_qty_value
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


def build_intent_orders(
    items: list[dict[str, Any]],
    *,
    order_type: str = "MKT",
    limit_price_map: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    normalized_order_type = validate_order_type(order_type or "MKT")
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            weight = float(item.get("weight"))
        except (TypeError, ValueError):
            continue
        side = "BUY" if weight >= 0 else "SELL"
        limit_price = None
        if is_limit_like(normalized_order_type) and limit_price_map is not None:
            picked = limit_price_map.get(symbol)
            if picked is not None:
                try:
                    picked_value = float(picked)
                except (TypeError, ValueError):
                    picked_value = None
                if picked_value is not None and picked_value > 0:
                    limit_price = picked_value
        orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": 0,
                "order_type": normalized_order_type,
                "limit_price": limit_price,
            }
        )
    return orders


def build_rebalance_orders(
    *,
    target_weights: dict[str, float],
    current_positions: dict[str, float],
    price_map: dict[str, float],
    portfolio_value: float,
    cash_buffer_ratio: float = 0.0,
    lot_size: int = 1,
    min_qty: int = 1,
    order_type: str = "MKT",
    epsilon: float = 1e-9,
) -> list[dict[str, Any]]:
    """Compile a delta rebalance plan from target weights and current positions.

    This mirrors Lean's `SetHoldings(targets, liquidateExistingHoldings=True)` behavior:
    - For symbols in `target_weights`, compute a *target* quantity from weights and prices.
    - For symbols not in targets but currently held, set target quantity to 0 (liquidate).
    - Emit orders for the difference between target and current quantities (BUY/SELL).

    Notes:
    - Quantities are computed as *absolute* quantities with an explicit `side` field.
      Signed quantities are handled at the order-intent layer.
    - We apply execution constraints (lot size + min qty) to the *target* sizing, not the delta,
      to avoid overselling/overbuying from rounding the delta.
    """
    normalized_order_type = validate_order_type(order_type or "MKT")
    try:
        pv_value = float(portfolio_value or 0.0)
    except (TypeError, ValueError):
        pv_value = 0.0
    if pv_value <= 0:
        return []

    try:
        buffer_value = float(cash_buffer_ratio or 0.0)
    except (TypeError, ValueError):
        buffer_value = 0.0
    buffer_value = min(max(buffer_value, 0.0), 1.0)
    effective_value = pv_value * (1.0 - buffer_value)

    lot = max(1, int(lot_size or 1))
    min_qty_value = max(1, int(min_qty or 1))
    if min_qty_value % lot != 0:
        min_qty_value = int(math.ceil(min_qty_value / lot)) * lot

    symbols: set[str] = set()
    for symbol in (target_weights or {}).keys():
        if symbol:
            symbols.add(str(symbol).strip().upper())
    for symbol, qty in (current_positions or {}).items():
        if not symbol:
            continue
        try:
            qty_value = float(qty or 0.0)
        except (TypeError, ValueError):
            qty_value = 0.0
        if abs(qty_value) > epsilon:
            symbols.add(str(symbol).strip().upper())

    orders: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        target_weight = float(target_weights.get(symbol, 0.0) or 0.0)
        try:
            current_qty = float(current_positions.get(symbol, 0.0) or 0.0)
        except (TypeError, ValueError):
            current_qty = 0.0

        target_qty = 0.0
        if abs(target_weight) > epsilon:
            price = price_map.get(symbol)
            if price is None or price <= 0:
                # Can't size the target without a price. Skip this symbol for now.
                continue
            raw_qty = abs(target_weight) * effective_value / float(price)
            sized = int(math.ceil(raw_qty / lot)) * lot
            if sized < min_qty_value:
                sized = min_qty_value
            target_qty = float(sized) if target_weight >= 0 else float(-sized)

        delta_qty = target_qty - current_qty
        if abs(delta_qty) <= epsilon:
            continue
        side = "BUY" if delta_qty > 0 else "SELL"
        quantity = abs(delta_qty)
        if quantity <= epsilon:
            continue
        orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": normalized_order_type,
                "limit_price": None,
                # Extra fields are useful for diagnostics/UI, but ignored by create_trade_order.
                "target_weight": target_weight,
                "target_qty": target_qty,
                "current_qty": current_qty,
                "delta_qty": delta_qty,
            }
        )

    return orders
