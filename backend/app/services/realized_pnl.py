from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from threading import Lock
import time as time_module
from typing import Iterable

from sqlalchemy import and_, func, or_

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


_REALIZED_PNL_CACHE_TTL_SECONDS = 2.0
_REALIZED_PNL_FAST_CACHE_TTL_SECONDS = 0.0
_REALIZED_PNL_CACHE_MAX_ENTRIES = 8
_REALIZED_PNL_CACHE_LOCK = Lock()
_REALIZED_PNL_CACHE: dict[str, tuple[float, RealizedPnlResult]] = {}
_REALIZED_PNL_FAST_CACHE: dict[str, tuple[float, RealizedPnlResult]] = {}


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


def _clone_result(result: RealizedPnlResult) -> RealizedPnlResult:
    return RealizedPnlResult(
        symbol_totals=dict(result.symbol_totals),
        order_totals=dict(result.order_totals),
        fill_totals=dict(result.fill_totals),
        baseline_at=result.baseline_at,
    )


def clear_realized_pnl_cache() -> None:
    with _REALIZED_PNL_CACHE_LOCK:
        _REALIZED_PNL_CACHE.clear()
        _REALIZED_PNL_FAST_CACHE.clear()


def _normalize_symbols(symbols: Iterable[str] | None) -> tuple[str, ...]:
    if not symbols:
        return tuple()
    normalized = {
        str(symbol or "").strip().upper()
        for symbol in symbols
        if str(symbol or "").strip()
    }
    return tuple(sorted(normalized))


def _build_baseline_cache_key(baseline: dict) -> str:
    items = []
    for item in baseline.get("items") or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            qty = float(item.get("position") or 0.0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            cost = float(item.get("avg_cost") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        items.append((symbol, qty, cost))
    items.sort()
    payload = {
        "created_at": str(baseline.get("created_at") or ""),
        "items": items,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _resolve_fill_revision_token(session) -> str | None:
    try:
        count_value, max_id, max_updated_at = (
            session.query(
                func.count(TradeFill.id),
                func.max(TradeFill.id),
                func.max(TradeFill.updated_at),
            )
            .one()
        )
    except Exception:
        return None
    updated_token = ""
    if isinstance(max_updated_at, datetime):
        updated_token = max_updated_at.isoformat()
    return f"{int(count_value or 0)}:{int(max_id or 0)}:{updated_token}"


def _query_fill_rows(
    session,
    *,
    baseline_at: datetime | None,
    symbols: tuple[str, ...] | None = None,
) -> list[tuple[TradeFill, TradeOrder]]:
    query = session.query(TradeFill, TradeOrder).join(TradeOrder, TradeFill.order_id == TradeOrder.id)
    if symbols:
        query = query.filter(TradeOrder.symbol.in_(list(symbols)))
    if baseline_at is not None:
        query = query.filter(
            or_(
                TradeFill.fill_time >= baseline_at,
                and_(TradeFill.fill_time.is_(None), TradeFill.created_at >= baseline_at),
            )
        )
    query = query.order_by(func.coalesce(TradeFill.fill_time, TradeFill.created_at).asc(), TradeFill.id.asc())
    return query.all()


def compute_realized_pnl(
    session,
    baseline: dict,
    *,
    use_cache: bool = True,
    cache_ttl_seconds: float = _REALIZED_PNL_CACHE_TTL_SECONDS,
    fast_cache_ttl_seconds: float = _REALIZED_PNL_FAST_CACHE_TTL_SECONDS,
    symbols: Iterable[str] | None = None,
) -> RealizedPnlResult:
    cache_key: str | None = None
    ttl_seconds = max(0.0, float(cache_ttl_seconds))
    fast_ttl_seconds = max(0.0, float(fast_cache_ttl_seconds))
    normalized_symbols = _normalize_symbols(symbols)
    symbol_set = set(normalized_symbols)
    fast_cache_key: str | None = None
    if use_cache:
        baseline_token = _build_baseline_cache_key(baseline)
        symbol_token = ",".join(normalized_symbols) if normalized_symbols else "*"
        fast_cache_key = f"{baseline_token}|symbols={symbol_token}"
        now_mono = time_module.monotonic()
        if fast_ttl_seconds > 0 and fast_cache_key:
            with _REALIZED_PNL_CACHE_LOCK:
                fast_cached = _REALIZED_PNL_FAST_CACHE.get(fast_cache_key)
            if fast_cached is not None:
                cached_at, cached_result = fast_cached
                if now_mono - cached_at <= fast_ttl_seconds:
                    return _clone_result(cached_result)
        fill_revision = _resolve_fill_revision_token(session)
        if fill_revision:
            cache_key = f"{fast_cache_key}|{fill_revision}"
            with _REALIZED_PNL_CACHE_LOCK:
                cached = _REALIZED_PNL_CACHE.get(cache_key)
            if cached is not None:
                cached_at, cached_result = cached
                if now_mono - cached_at <= ttl_seconds:
                    return _clone_result(cached_result)

    baseline_at = _parse_time(str(baseline.get("created_at") or ""))
    symbol_totals: dict[str, float] = {}
    order_totals: dict[int, float] = {}
    fill_totals: dict[int, float] = {}
    lots: dict[str, list[Lot]] = {}

    for item in baseline.get("items") or []:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        if symbol_set and symbol not in symbol_set:
            continue
        qty = float(item.get("position") or 0.0)
        if qty == 0:
            continue
        cost = float(item.get("avg_cost") or 0.0)
        lots.setdefault(symbol, []).append(Lot(qty=qty, cost=cost))
        symbol_totals.setdefault(symbol, 0.0)

    rows = _query_fill_rows(
        session,
        baseline_at=baseline_at,
        symbols=normalized_symbols or None,
    )

    def effective_time(fill: TradeFill) -> datetime | None:
        return _ensure_aware(fill.fill_time or fill.created_at)

    for fill, order in rows:
        symbol = (order.symbol or "").strip().upper()
        if not symbol:
            continue
        if symbol_set and symbol not in symbol_set:
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

    result = RealizedPnlResult(
        symbol_totals=symbol_totals,
        order_totals=order_totals,
        fill_totals=fill_totals,
        baseline_at=baseline_at,
    )
    if use_cache and cache_key:
        now_mono = time_module.monotonic()
        with _REALIZED_PNL_CACHE_LOCK:
            _REALIZED_PNL_CACHE[cache_key] = (now_mono, _clone_result(result))
            if fast_cache_key:
                _REALIZED_PNL_FAST_CACHE[fast_cache_key] = (now_mono, _clone_result(result))
            if len(_REALIZED_PNL_CACHE) > _REALIZED_PNL_CACHE_MAX_ENTRIES:
                stale_keys = sorted(_REALIZED_PNL_CACHE.items(), key=lambda item: item[1][0])[
                    : len(_REALIZED_PNL_CACHE) - _REALIZED_PNL_CACHE_MAX_ENTRIES
                ]
                for stale_key, _ in stale_keys:
                    _REALIZED_PNL_CACHE.pop(stale_key, None)
            if len(_REALIZED_PNL_FAST_CACHE) > _REALIZED_PNL_CACHE_MAX_ENTRIES:
                stale_fast_keys = sorted(_REALIZED_PNL_FAST_CACHE.items(), key=lambda item: item[1][0])[
                    : len(_REALIZED_PNL_FAST_CACHE) - _REALIZED_PNL_CACHE_MAX_ENTRIES
                ]
                for stale_key, _ in stale_fast_keys:
                    _REALIZED_PNL_FAST_CACHE.pop(stale_key, None)
    return result
