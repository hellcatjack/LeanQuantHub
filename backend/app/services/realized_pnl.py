from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import TradeFill, TradeOrder


@dataclass
class RealizedPnlResult:
    symbol_totals: dict[str, float]
    order_totals: dict[int, float]
    fill_totals: dict[int, float]
    baseline_at: datetime | None


@dataclass
class Lot:
    qty: float
    cost: float


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ensure_aware(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def compute_realized_pnl(session, baseline: dict) -> RealizedPnlResult:
    baseline_at = _parse_time(str(baseline.get("created_at") or ""))
    symbol_totals: dict[str, float] = {}
    order_totals: dict[int, float] = {}
    fill_totals: dict[int, float] = {}
    lots: dict[str, list[Lot]] = {}

    for item in baseline.get("items") or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        qty = float(item.get("position") or 0.0)
        if qty == 0:
            continue
        cost = float(item.get("avg_cost") or 0.0)
        lots.setdefault(symbol, []).append(Lot(qty=qty, cost=cost))
        symbol_totals.setdefault(symbol, 0.0)

    rows = (
        session.query(TradeFill, TradeOrder)
        .join(TradeOrder, TradeFill.order_id == TradeOrder.id)
        .all()
    )

    def effective_time(fill: TradeFill) -> datetime | None:
        return _ensure_aware(fill.fill_time or fill.created_at)

    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    rows = sorted(rows, key=lambda r: (effective_time(r[0]) or min_dt))

    for fill, order in rows:
        symbol = (order.symbol or "").strip().upper()
        if not symbol:
            continue
        dt = effective_time(fill)
        if baseline_at and dt and dt < baseline_at:
            continue
        side = (order.side or "").strip().upper()
        qty = abs(float(fill.fill_quantity or 0.0))
        if qty <= 0:
            continue
        price = float(fill.fill_price or 0.0)
        commission = float(fill.commission or 0.0)
        commission_per_share = commission / qty if qty else 0.0

        symbol_totals.setdefault(symbol, 0.0)
        order_totals.setdefault(order.id, 0.0)

        def realize(amount: float) -> None:
            symbol_totals[symbol] += amount
            order_totals[order.id] += amount
            fill_totals[fill.id] = fill_totals.get(fill.id, 0.0) + amount

        fifo = lots.setdefault(symbol, [])
        remaining = qty

        if side == "BUY":
            while remaining > 0 and fifo and fifo[0].qty < 0:
                lot = fifo[0]
                match_qty = min(remaining, abs(lot.qty))
                realized = (lot.cost - price) * match_qty - commission_per_share * match_qty
                realize(realized)
                lot.qty += match_qty
                remaining -= match_qty
                if abs(lot.qty) < 1e-9:
                    fifo.pop(0)
            if remaining > 0:
                open_cost = price + commission_per_share
                fifo.append(Lot(qty=remaining, cost=open_cost))
        elif side == "SELL":
            while remaining > 0 and fifo and fifo[0].qty > 0:
                lot = fifo[0]
                match_qty = min(remaining, lot.qty)
                realized = (price - lot.cost) * match_qty - commission_per_share * match_qty
                realize(realized)
                lot.qty -= match_qty
                remaining -= match_qty
                if lot.qty <= 1e-9:
                    fifo.pop(0)
            if remaining > 0:
                open_cost = price - commission_per_share
                fifo.append(Lot(qty=-remaining, cost=open_cost))
        else:
            continue

    return RealizedPnlResult(
        symbol_totals=symbol_totals,
        order_totals=order_totals,
        fill_totals=fill_totals,
        baseline_at=baseline_at,
    )
