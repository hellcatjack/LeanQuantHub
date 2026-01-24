from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func

from app.models import TradeFill, TradeGuardState, TradeOrder, TradeRun, TradeSettings
from app.services.lean_market import fetch_market_snapshots
from app.services.lean_bridge import read_quote


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _pick_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    for key in ("last", "close", "bid", "ask"):
        value = snapshot.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _read_local_snapshot(symbol: str) -> dict[str, Any] | None:
    payload = read_quote(symbol)
    if not isinstance(payload, dict):
        return None
    if not payload:
        return None
    if payload.get("symbol") and len(payload.keys()) == 1:
        return None
    return payload


def _resolve_trade_date() -> date:
    return datetime.utcnow().date()


def get_or_create_guard_state(
    session,
    *,
    project_id: int,
    mode: str,
    trade_date: date | None = None,
) -> TradeGuardState:
    trade_date = trade_date or _resolve_trade_date()
    row = (
        session.query(TradeGuardState)
        .filter(
            TradeGuardState.project_id == project_id,
            TradeGuardState.trade_date == trade_date,
            TradeGuardState.mode == mode,
        )
        .one_or_none()
    )
    if row:
        return row
    row = TradeGuardState(project_id=project_id, trade_date=trade_date, mode=mode)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def record_guard_event(
    session,
    *,
    project_id: int,
    mode: str,
    event: str,
    trade_date: date | None = None,
    count: int = 1,
) -> TradeGuardState:
    state = get_or_create_guard_state(session, project_id=project_id, mode=mode, trade_date=trade_date)
    if event == "order_failure":
        state.order_failures = int(state.order_failures or 0) + count
    elif event == "market_data_error":
        state.market_data_errors = int(state.market_data_errors or 0) + count
    state.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(state)
    return state


def _merge_risk_params(defaults: dict[str, Any] | None, overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(defaults, dict):
        merged.update(defaults)
    if isinstance(overrides, dict):
        merged.update(overrides)
    return merged


def _load_positions(session, *, project_id: int, mode: str) -> dict[str, float]:
    positions: dict[str, float] = defaultdict(float)
    rows = (
        session.query(TradeOrder.symbol, TradeOrder.side, func.sum(TradeFill.fill_quantity))
        .join(TradeFill, TradeFill.order_id == TradeOrder.id)
        .join(TradeRun, TradeRun.id == TradeOrder.run_id)
        .filter(
            TradeRun.project_id == project_id,
            TradeRun.mode == mode,
        )
        .group_by(TradeOrder.symbol, TradeOrder.side)
        .all()
    )
    for symbol, side, qty in rows:
        if not symbol or qty is None:
            continue
        sign = 1.0 if (side or "").upper() == "BUY" else -1.0
        positions[str(symbol).upper()] += sign * float(qty)
    return {symbol: qty for symbol, qty in positions.items() if qty != 0}


def _resolve_prices(
    session,
    symbols: list[str],
    *,
    stale_seconds: int,
    price_map: dict[str, float] | None,
) -> tuple[dict[str, float], str, int]:
    resolved: dict[str, float] = {}
    errors = 0
    source = "ib"
    now = datetime.utcnow()

    if not symbols:
        return resolved, "none", errors

    if price_map:
        for symbol, price in price_map.items():
            try:
                resolved[str(symbol).upper()] = float(price)
            except (TypeError, ValueError):
                continue
        if resolved:
            return resolved, source, errors

    snapshots = fetch_market_snapshots(
        session,
        symbols=symbols,
        store=False,
        fallback_history=True,
        history_duration="5 D",
        history_bar_size="1 day",
        history_use_rth=True,
    )
    snapshot_map = {item.get("symbol"): item for item in snapshots}

    for symbol in symbols:
        payload = (snapshot_map.get(symbol) or {}).get("data") or None
        price = _pick_price(payload)
        ts = _parse_timestamp((payload or {}).get("timestamp"))
        if price is not None and ts:
            if now - ts <= timedelta(seconds=stale_seconds):
                resolved[symbol] = price
                continue
        local = _read_local_snapshot(symbol)
        local_price = _pick_price(local)
        if local_price is not None:
            resolved[symbol] = local_price
            source = "local"
        else:
            errors += 1

    return resolved, source, errors


def evaluate_intraday_guard(
    session,
    *,
    project_id: int,
    mode: str,
    risk_params: dict[str, Any] | None = None,
    price_map: dict[str, float] | None = None,
    trade_date: date | None = None,
) -> dict[str, Any]:
    state = get_or_create_guard_state(session, project_id=project_id, mode=mode, trade_date=trade_date)
    settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
    defaults = settings_row.risk_defaults if settings_row else {}
    risk_params = _merge_risk_params(defaults, risk_params)

    stale_seconds = int(risk_params.get("valuation_stale_seconds") or 120)

    positions = _load_positions(session, project_id=project_id, mode=mode)
    symbols = sorted(positions.keys())
    prices, valuation_source, market_errors = _resolve_prices(
        session,
        symbols,
        stale_seconds=stale_seconds,
        price_map=price_map,
    )

    if market_errors:
        state.market_data_errors = int(state.market_data_errors or 0) + market_errors

    cash_available = float(risk_params.get("cash_available") or 0.0)
    equity = cash_available
    for symbol, qty in positions.items():
        price = prices.get(symbol)
        if price is None:
            continue
        equity += qty * price

    now = datetime.utcnow()
    if state.day_start_equity is None and equity > 0:
        state.day_start_equity = equity
    if state.equity_peak is None and equity > 0:
        state.equity_peak = equity
    if equity > 0 and state.equity_peak is not None:
        state.equity_peak = max(state.equity_peak, equity)

    state.last_equity = equity if equity > 0 else state.last_equity
    state.last_valuation_ts = now
    state.valuation_source = valuation_source

    reasons: list[str] = []
    day_start = state.day_start_equity or 0.0
    peak = state.equity_peak or 0.0
    if day_start > 0:
        daily_loss = (equity - day_start) / day_start
        max_daily_loss = risk_params.get("max_daily_loss")
        if max_daily_loss is not None and daily_loss <= float(max_daily_loss):
            reasons.append("max_daily_loss")
    if peak > 0:
        drawdown = (equity - peak) / peak
        max_intraday_drawdown = risk_params.get("max_intraday_drawdown")
        if max_intraday_drawdown is not None and drawdown <= -abs(float(max_intraday_drawdown)):
            reasons.append("max_intraday_drawdown")

    max_order_failures = risk_params.get("max_order_failures")
    if max_order_failures is not None and (state.order_failures or 0) >= int(max_order_failures):
        reasons.append("max_order_failures")

    max_market_errors = risk_params.get("max_market_data_errors")
    if max_market_errors is not None and (state.market_data_errors or 0) >= int(max_market_errors):
        reasons.append("max_market_data_errors")

    max_risk_triggers = risk_params.get("max_risk_triggers")
    if max_risk_triggers is not None and (state.risk_triggers or 0) >= int(max_risk_triggers):
        reasons.append("max_risk_triggers")

    if reasons and state.status != "halted":
        state.status = "halted"
        state.risk_triggers = int(state.risk_triggers or 0) + 1
        cooldown_seconds = int(risk_params.get("cooldown_seconds") or 0)
        if cooldown_seconds > 0:
            state.cooldown_until = now + timedelta(seconds=cooldown_seconds)
        state.halt_reason = {
            "reasons": reasons,
            "triggered_at": now.isoformat(timespec="seconds"),
        }

    state.updated_at = now
    session.commit()
    session.refresh(state)

    return {
        "status": state.status,
        "reason": state.halt_reason,
        "valuation_source": state.valuation_source,
        "equity": state.last_equity,
    }
