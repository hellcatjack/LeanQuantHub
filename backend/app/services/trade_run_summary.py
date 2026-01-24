from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import csv
from typing import Any

from app.models import DecisionSnapshot, TradeFill, TradeOrder, TradeRun


def _read_snapshot_weights(items_path: str | None) -> dict[str, float]:
    if not items_path:
        return {}
    path = Path(items_path)
    if not path.exists():
        return {}
    weights: dict[str, float] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = (row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                try:
                    weight = float(row.get("weight"))
                except (TypeError, ValueError):
                    continue
                weights[symbol] = weight
    except OSError:
        return {}
    return weights


def _max_datetime(values: list[datetime | None]) -> datetime | None:
    filtered = [value for value in values if value is not None]
    return max(filtered) if filtered else None


def build_trade_run_detail(session, run_id: int, *, limit: int = 200, offset: int = 0):
    run = session.get(TradeRun, run_id)
    if not run:
        raise ValueError("trade_run_not_found")
    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id == run_id)
        .order_by(TradeOrder.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    fills = (
        session.query(TradeFill)
        .join(TradeOrder, TradeFill.order_id == TradeOrder.id)
        .filter(TradeOrder.run_id == run_id)
        .order_by(TradeFill.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    last_update_at = _max_datetime(
        [run.updated_at]
        + [order.updated_at for order in orders]
        + [fill.updated_at for fill in fills]
    )
    return run, orders, fills, last_update_at


def build_symbol_summary(session, run_id: int) -> list[dict[str, Any]]:
    run = session.get(TradeRun, run_id)
    if not run:
        raise ValueError("trade_run_not_found")
    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id == run_id)
        .order_by(TradeOrder.id.asc())
        .all()
    )
    order_map = {order.id: order for order in orders}
    fills = (
        session.query(TradeFill)
        .filter(TradeFill.order_id.in_(list(order_map.keys()) or [-1]))
        .order_by(TradeFill.id.asc())
        .all()
    )

    snapshot = None
    if run.decision_snapshot_id:
        snapshot = session.get(DecisionSnapshot, run.decision_snapshot_id)
    weights = _read_snapshot_weights(snapshot.items_path if snapshot else None)
    params = run.params or {}
    portfolio_value = 0.0
    try:
        portfolio_value = float(params.get("portfolio_value") or 0.0)
    except (TypeError, ValueError):
        portfolio_value = 0.0

    totals_qty: dict[str, float] = defaultdict(float)
    filled_qty: dict[str, float] = defaultdict(float)
    filled_value: dict[str, float] = defaultdict(float)
    last_status: dict[str, str | None] = {}
    last_status_at: dict[str, datetime | None] = {}

    for order in orders:
        symbol = (order.symbol or "").strip().upper()
        if not symbol:
            continue
        totals_qty[symbol] += float(order.quantity or 0.0)
        updated_at = order.updated_at or order.created_at
        prev_at = last_status_at.get(symbol)
        if prev_at is None or (updated_at and updated_at > prev_at):
            last_status_at[symbol] = updated_at
            last_status[symbol] = order.status

    for fill in fills:
        order = order_map.get(fill.order_id)
        if not order:
            continue
        symbol = (order.symbol or "").strip().upper()
        if not symbol:
            continue
        qty = float(fill.fill_quantity or 0.0)
        price = float(fill.fill_price or 0.0)
        side = (order.side or "").strip().upper()
        sign = 1.0 if side != "SELL" else -1.0
        filled_qty[symbol] += qty
        filled_value[symbol] += sign * qty * price

    symbols = sorted(set(list(weights.keys()) + list(totals_qty.keys())))
    summary: list[dict[str, Any]] = []
    for symbol in symbols:
        total_qty = totals_qty.get(symbol, 0.0)
        filled = filled_qty.get(symbol, 0.0)
        value_filled = filled_value.get(symbol, 0.0)
        avg_price = value_filled / filled if filled > 0 else None
        weight = weights.get(symbol)
        target_value = None
        if weight is not None and portfolio_value > 0:
            target_value = portfolio_value * float(weight)
        delta_value = None
        delta_weight = None
        if target_value is not None:
            delta_value = target_value - value_filled
            if portfolio_value > 0:
                delta_weight = delta_value / portfolio_value
        fill_ratio = None
        if total_qty > 0:
            fill_ratio = filled / total_qty
        summary.append(
            {
                "symbol": symbol,
                "target_weight": weight,
                "target_value": target_value,
                "filled_qty": filled,
                "avg_fill_price": avg_price,
                "filled_value": value_filled,
                "pending_qty": max(total_qty - filled, 0.0),
                "last_status": last_status.get(symbol),
                "delta_value": delta_value,
                "delta_weight": delta_weight,
                "fill_ratio": fill_ratio,
            }
        )
    return summary


def build_last_update_at(session, run_id: int) -> datetime | None:
    run = session.get(TradeRun, run_id)
    if not run:
        return None
    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id == run_id)
        .order_by(TradeOrder.updated_at.desc())
        .limit(1)
        .all()
    )
    fills = (
        session.query(TradeFill)
        .join(TradeOrder, TradeFill.order_id == TradeOrder.id)
        .filter(TradeOrder.run_id == run_id)
        .order_by(TradeFill.updated_at.desc())
        .limit(1)
        .all()
    )
    return _max_datetime(
        [run.updated_at]
        + [order.updated_at for order in orders]
        + [fill.updated_at for fill in fills]
    )
