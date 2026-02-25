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
    deadband_min_notional: float = 0.0,
    deadband_min_weight: float = 0.0,
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
    - Delta is then quantized to whole lots (towards zero) before generating an order. This
      matches Lean/QuantConnect behavior that ignores sub-lot residuals in execution, and
      prevents crossing through the target with a forced one-lot sell/buy.
    - Optional deadband thresholds can suppress tiny lot-valid deltas:
      - `deadband_min_notional`: minimum order notional in account currency
      - `deadband_min_weight`: minimum order notional / portfolio_value
      Defaults are zero (disabled) to preserve existing behavior.
    """
    normalized_order_type = validate_order_type(order_type or "MKT")
    try:
        pv_value = float(portfolio_value or 0.0)
    except (TypeError, ValueError):
        pv_value = 0.0
    if pv_value <= 0:
        return []

    try:
        deadband_notional = float(deadband_min_notional or 0.0)
    except (TypeError, ValueError):
        deadband_notional = 0.0
    deadband_notional = max(0.0, deadband_notional)

    try:
        deadband_weight = float(deadband_min_weight or 0.0)
    except (TypeError, ValueError):
        deadband_weight = 0.0
    deadband_weight = max(0.0, deadband_weight)

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

        raw_delta_qty = target_qty - current_qty
        if abs(raw_delta_qty) <= epsilon:
            continue

        # Keep the order delta monotonic towards target:
        # - never exceed the requested delta
        # - ignore sub-lot residuals
        # This mirrors Lean's lot-size handling for target deltas.
        tradable_lots = int(math.floor((abs(raw_delta_qty) + epsilon) / float(lot)))
        if tradable_lots <= 0:
            continue
        delta_qty = float(tradable_lots * lot)
        if raw_delta_qty < 0:
            delta_qty = -delta_qty

        side = "BUY" if delta_qty > 0 else "SELL"
        quantity = abs(delta_qty)
        if quantity <= epsilon:
            continue

        order_notional = None
        order_weight = None
        if deadband_notional > epsilon or deadband_weight > epsilon:
            price = price_map.get(symbol)
            if price is not None:
                try:
                    price_value = float(price)
                except (TypeError, ValueError):
                    price_value = 0.0
                if price_value > 0:
                    order_notional = quantity * price_value
                    order_weight = order_notional / pv_value if pv_value > 0 else 0.0
                    if deadband_notional > epsilon and order_notional + epsilon < deadband_notional:
                        continue
                    if deadband_weight > epsilon and order_weight + epsilon < deadband_weight:
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
                "raw_delta_qty": raw_delta_qty,
                "order_notional": order_notional,
                "order_weight": order_weight,
            }
        )

    return orders
