from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import csv
from typing import Any

from app.core.config import settings
from app.models import DecisionSnapshot, TradeFill, TradeOrder, TradeRun
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_positions, read_quotes
from app.services.realized_pnl import compute_realized_pnl
from app.services.realized_pnl_baseline import ensure_positions_baseline


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


def _pick_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    for key in ("last", "close", "bid", "ask"):
        value = snapshot.get(key)
        if value is None:
            continue
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue
        if value_f > 0:
            return value_f
    return None


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    return Path("/data/share/stock/data")


def _normalize_symbol_for_filename(symbol: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in symbol.upper()).strip("_")


def _find_latest_price_file(root: Path, symbol: str) -> Path | None:
    if not root.exists():
        return None
    normalized = _normalize_symbol_for_filename(symbol)
    if not normalized:
        return None
    matches = sorted(root.glob(f"*_{normalized}_Daily.csv"))
    if not matches:
        return None
    return matches[-1]


def _read_latest_close(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            last_row: dict[str, Any] | None = None
            for row in reader:
                last_row = row
        if not last_row:
            return None
        close_value = last_row.get("close")
        if close_value is None or close_value == "":
            return None
        value = float(close_value)
        return value if value > 0 else None
    except (OSError, ValueError, TypeError):
        return None


def _load_fallback_prices(symbols: list[str]) -> dict[str, float]:
    root = _resolve_data_root() / "curated_adjusted"
    prices: dict[str, float] = {}
    for symbol in symbols:
        path = _find_latest_price_file(root, symbol)
        if not path:
            continue
        value = _read_latest_close(path)
        if value is None:
            continue
        prices[symbol] = value
    return prices


def _build_price_map(symbols: list[str]) -> dict[str, float]:
    symbol_set = {str(symbol or "").strip().upper() for symbol in symbols if symbol}
    if not symbol_set:
        return {}
    quotes = read_quotes(resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    prices: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol not in symbol_set:
            continue
        picked = _pick_price(item)
        if picked is not None:
            prices[symbol] = picked
    missing = sorted(symbol_set - set(prices.keys()))
    if missing:
        prices.update(_load_fallback_prices(missing))
    return prices


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
        # Live-trade monitor expects fills grouped by newest order ids first.
        .order_by(TradeFill.order_id.desc(), TradeFill.created_at.desc(), TradeFill.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    order_map = {order.id: order for order in orders}

    positions_payload = read_positions(resolve_bridge_root())
    baseline = ensure_positions_baseline(resolve_bridge_root(), positions_payload)
    realized = compute_realized_pnl(session, baseline)

    order_payloads: list[dict[str, Any]] = []
    for order in orders:
        order_payloads.append(
            {
                "id": order.id,
                "run_id": order.run_id,
                "client_order_id": order.client_order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "order_type": order.order_type,
                "limit_price": order.limit_price,
                "status": order.status,
                "filled_quantity": order.filled_quantity,
                "avg_fill_price": order.avg_fill_price,
                "ib_order_id": order.ib_order_id,
                "ib_perm_id": order.ib_perm_id,
                "rejected_reason": order.rejected_reason,
                "realized_pnl": realized.order_totals.get(order.id, 0.0),
                "params": order.params,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
            }
        )

    fill_payloads: list[dict[str, Any]] = []
    for fill in fills:
        order = order_map.get(fill.order_id)
        fill_payloads.append(
            {
                "id": fill.id,
                "order_id": fill.order_id,
                "symbol": order.symbol if order else None,
                "side": order.side if order else None,
                "exec_id": fill.exec_id,
                "fill_quantity": fill.fill_quantity,
                "fill_price": fill.fill_price,
                "commission": fill.commission,
                "realized_pnl": realized.fill_totals.get(fill.id, 0.0),
                "fill_time": fill.fill_time,
                "currency": fill.currency,
                "exchange": fill.exchange,
            }
        )
    last_update_at = _max_datetime(
        [run.updated_at]
        + [order.updated_at for order in orders]
        + [fill.updated_at for fill in fills]
    )
    return run, order_payloads, fill_payloads, last_update_at


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

    positions_payload = read_positions(resolve_bridge_root())
    positions_items = (
        positions_payload.get("items") if isinstance(positions_payload.get("items"), list) else []
    )
    current_qty: dict[str, float] = {}
    current_market_value: dict[str, float] = {}
    for item in positions_items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        qty_value = item.get("quantity")
        if qty_value is None:
            qty_value = item.get("position")
        if qty_value is None:
            continue
        try:
            qty = float(qty_value)
        except (TypeError, ValueError):
            continue
        if abs(qty) <= 1e-12:
            continue
        current_qty[symbol] = qty
        mv_value = item.get("market_value")
        if mv_value is not None:
            try:
                mv = float(mv_value)
            except (TypeError, ValueError):
                mv = None
            # Lean bridge may emit market_value=0 even when holdings exist (missing market data).
            # Treat zero/near-zero as unknown and fall back to latest quotes.
            if mv is not None and abs(mv) > 1e-12:
                current_market_value[symbol] = mv
        if symbol not in current_market_value:
            market_price_value = item.get("market_price")
            if market_price_value is not None:
                try:
                    market_price = float(market_price_value)
                except (TypeError, ValueError):
                    market_price = None
                if market_price is not None and market_price != 0:
                    current_market_value[symbol] = float(qty) * market_price

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

    symbols = sorted(set(list(weights.keys()) + list(totals_qty.keys()) + list(current_qty.keys())))
    price_map = _build_price_map(symbols)
    summary: list[dict[str, Any]] = []
    for symbol in symbols:
        total_qty = totals_qty.get(symbol, 0.0)
        filled = filled_qty.get(symbol, 0.0)
        value_filled = filled_value.get(symbol, 0.0)
        avg_price = value_filled / filled if filled > 0 else None
        weight = weights.get(symbol)
        if weight is None:
            weight = 0.0
        target_value = portfolio_value * float(weight) if portfolio_value > 0 else None

        qty_now = current_qty.get(symbol, 0.0)
        current_value = current_market_value.get(symbol)
        if (current_value is None or abs(float(current_value)) <= 1e-12) and abs(float(qty_now)) > 1e-12:
            px = price_map.get(symbol)
            current_value = float(qty_now) * float(px) if px is not None and px > 0 else None
        current_weight = None
        if current_value is not None and portfolio_value > 0:
            current_weight = current_value / portfolio_value
        delta_value = None
        delta_weight = None
        if target_value is not None and current_value is not None:
            delta_value = target_value - current_value
            if current_weight is not None:
                delta_weight = float(weight) - float(current_weight)
        fill_ratio = None
        if total_qty > 0:
            fill_ratio = filled / total_qty
        summary.append(
            {
                "symbol": symbol,
                "target_weight": weight,
                "target_value": target_value,
                "current_qty": qty_now,
                "current_value": current_value,
                "current_weight": current_weight,
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
