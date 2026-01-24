from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import csv

from app.core.config import settings
from app.db import SessionLocal
from app.models import DecisionSnapshot, TradeFill, TradeOrder, TradeRun, TradeSettings
from pathlib import Path

from app.services.ib_market import fetch_market_snapshots
from app.services.ib_order_executor import IBOrderExecutor
from app.services.ib_settings import ensure_ib_client_id, probe_ib_connection, resolve_ib_api_mode
from app.services.job_lock import JobLock
from app.services.trade_guard import (
    _read_local_snapshot,
    get_or_create_guard_state,
    record_guard_event,
)
from app.services.ib_orders import apply_fill_to_order
from app.services.trade_order_builder import build_orders
from app.services.trade_orders import create_trade_order, update_trade_order_status
from app.services.trade_risk_engine import evaluate_orders
from app.services.trade_alerts import notify_trade_alert
from app.services.ib_account import fetch_account_summary
from app.services.trade_order_intent import write_order_intent


ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")


@dataclass
class TradeExecutionResult:
    run_id: int
    status: str
    filled: int
    cancelled: int
    rejected: int
    skipped: int
    message: str | None
    dry_run: bool


def _pick_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    for key in ("last", "close", "bid", "ask"):
        value = snapshot.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _limit_allows_fill(side: str, price: float, limit_price: float) -> bool:
    if side == "BUY":
        return price <= limit_price
    if side == "SELL":
        return price >= limit_price
    return False


def _resolve_snapshot_price(symbol: str, snapshot_map: dict[str, dict[str, Any]]) -> float | None:
    payload = (snapshot_map.get(symbol) or {}).get("data")
    price = _pick_price(payload)
    if price is not None:
        return price
    local_snapshot = _read_local_snapshot(symbol)
    return _pick_price(local_snapshot)


def _submit_ib_orders(session, orders, *, price_map):
    settings_row = ensure_ib_client_id(session)
    executor = IBOrderExecutor(settings_row)
    return executor.submit_orders(session, orders, price_map=price_map)


def _execute_orders_with_ib(session, run, orders, *, price_map):
    result = _submit_ib_orders(session, orders, price_map=price_map)
    events = []
    if isinstance(result, dict):
        events = result.get("events") or []
    order_map = {order.id: order for order in orders}
    now = datetime.utcnow()
    for event in events:
        order = order_map.get(getattr(event, "order_id", None))
        if not order:
            continue
        ib_order_id = getattr(event, "ib_order_id", None)
        if ib_order_id:
            order.ib_order_id = ib_order_id
        status = str(getattr(event, "status", "") or "").strip().upper()
        if status in {"SUBMITTED", "PRESUBMITTED"}:
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
            continue
        if status == "REJECTED":
            update_trade_order_status(
                session,
                order,
                {"status": "REJECTED", "params": {"reason": "ib_rejected"}},
            )
            continue
        if status in {"PARTIAL", "FILLED"}:
            fill_qty = float(getattr(event, "filled", 0.0) or 0.0)
            if fill_qty <= 0:
                fill_qty = float(order.quantity)
            fill_price = getattr(event, "avg_price", None)
            if fill_price is None:
                fill_price = price_map.get(order.symbol)
            if fill_price is not None:
                apply_fill_to_order(
                    session,
                    order,
                    fill_qty=fill_qty,
                    fill_price=float(fill_price),
                    fill_time=now,
                    exec_id=getattr(event, "exec_id", None),
                )
            else:
                update_trade_order_status(
                    session,
                    order,
                    {"status": "SUBMITTED", "params": {"warn": "fill_price_missing"}},
                )
    return result


def _finalize_run_status(session, run, *, filled: int, rejected: int, cancelled: int):
    if filled == 0:
        run.status = "failed"
    elif rejected or cancelled:
        run.status = "partial"
    else:
        run.status = "done"
    run.ended_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    session.commit()


def _read_decision_items(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows: list[dict[str, Any]] = []
            for row in csv.DictReader(handle):
                symbol = (row.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "weight": row.get("weight"),
                    }
                )
            return rows
    except OSError:
        return []


def _build_client_order_id(run_id: int, snapshot_id: int | None, symbol: str, side: str) -> str:
    base = f"{run_id}:{symbol}:{side}"
    if snapshot_id:
        return f"{base}:{snapshot_id}"
    return base


def _merge_risk_params(defaults: dict[str, Any] | None, overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(defaults, dict):
        merged.update(defaults)
    if isinstance(overrides, dict):
        merged.update(overrides)
    return merged


def _ib_connection_ok(session) -> bool:
    state = probe_ib_connection(session)
    return (state.status or "").lower() in {"connected", "mock"}


def execute_trade_run(
    run_id: int,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> TradeExecutionResult:
    session = SessionLocal()
    lock = JobLock("trade_execution", Path(settings.data_root) if settings.data_root else None)
    if not lock.acquire():
        session.close()
        raise RuntimeError("trade_execution_lock_busy")
    run: TradeRun | None = None
    try:
        run = session.get(TradeRun, run_id)
        if not run:
            raise RuntimeError("trade_run_not_found")
        if run.status not in {"queued", "blocked", "failed"}:
            raise RuntimeError("trade_run_status_invalid")
        if run.status != "queued" and not force:
            raise RuntimeError("trade_run_not_queued")

        guard_state = get_or_create_guard_state(
            session,
            project_id=run.project_id,
            mode=run.mode,
        )
        if guard_state.status == "halted" and not force:
            run.status = "blocked"
            run.message = "guard_halted"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            notify_trade_alert(session, f"Trade run blocked: guard halted (run={run.id})")
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
        execution_source = (settings_row.execution_data_source if settings_row else "ib") or "ib"
        if execution_source.lower() != "ib":
            params = dict(run.params or {})
            params["execution_data_source"] = execution_source
            params["expected_execution_data_source"] = "ib"
            run.status = "blocked"
            run.message = "execution_data_source_mismatch"
            run.params = params
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        if not _ib_connection_ok(session):
            run.status = "blocked"
            run.message = "connection_unavailable"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            notify_trade_alert(session, f"Trade run blocked: IB connection unavailable (run={run.id})")
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        )
        if run.decision_snapshot_id is None:
            run.status = "blocked"
            run.message = "decision_snapshot_required"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )
        snapshot_map: dict[str, dict[str, Any]] = {}
        price_map: dict[str, float] = {}
        params = dict(run.params or {})
        if not orders:
            snapshot = session.get(DecisionSnapshot, run.decision_snapshot_id)
            if snapshot is None or not snapshot.items_path:
                run.status = "failed"
                run.message = "decision_snapshot_items_missing"
                run.ended_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )
            items = _read_decision_items(snapshot.items_path)
            if not items:
                run.status = "failed"
                run.message = "decision_snapshot_items_empty"
                run.ended_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )

            intent_path = write_order_intent(
                session,
                snapshot_id=run.decision_snapshot_id,
                items=items,
                output_dir=ARTIFACT_ROOT / "order_intents",
            )
            params["order_intent_path"] = intent_path
            run.params = params
            run.updated_at = datetime.utcnow()
            session.commit()

            symbols = sorted({item.get("symbol") for item in items if item.get("symbol")})
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
                price = _resolve_snapshot_price(symbol, snapshot_map)
                if price is not None:
                    price_map[symbol] = price

            if "portfolio_value" not in params:
                account_summary = fetch_account_summary(session)
                if isinstance(account_summary, dict):
                    net_liq = account_summary.get("NetLiquidation")
                    if net_liq is not None:
                        try:
                            portfolio_value = float(net_liq)
                        except (TypeError, ValueError):
                            portfolio_value = 0.0
                        if portfolio_value > 0:
                            params["portfolio_value"] = portfolio_value
                            run.params = params
                            run.updated_at = datetime.utcnow()
                            session.commit()
                    cash_available = account_summary.get("cash_available")
                    if cash_available is not None:
                        params.setdefault("cash_available", cash_available)
            portfolio_value = float(params.get("portfolio_value") or 0.0)
            if portfolio_value <= 0:
                run.status = "failed"
                run.message = "portfolio_value_required"
                run.ended_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )
            cash_buffer_ratio = float(params.get("cash_buffer_ratio") or 0.0)
            lot_size = int(params.get("lot_size") or 1)
            order_type = str(params.get("order_type") or "MKT")
            limit_price = params.get("limit_price")

            draft_orders = build_orders(
                items,
                price_map=price_map,
                portfolio_value=portfolio_value,
                cash_buffer_ratio=cash_buffer_ratio,
                lot_size=lot_size,
                order_type=order_type,
                limit_price=limit_price,
            )
            if not draft_orders:
                run.status = "failed"
                run.message = "orders_empty"
                run.ended_at = datetime.utcnow()
                session.commit()
                return TradeExecutionResult(
                    run_id=run.id,
                    status=run.status,
                    filled=0,
                    cancelled=0,
                    rejected=0,
                    skipped=0,
                    message=run.message,
                    dry_run=dry_run,
                )

            created = 0
            for draft in draft_orders:
                client_order_id = _build_client_order_id(
                    run.id,
                    run.decision_snapshot_id,
                    str(draft.get("symbol")),
                    str(draft.get("side")),
                )
                payload = dict(draft)
                payload["client_order_id"] = client_order_id
                payload["params"] = {
                    "source": "decision_snapshot",
                    "decision_snapshot_id": run.decision_snapshot_id,
                }
                result = create_trade_order(session, payload, run_id=run.id)
                if result.created:
                    created += 1
            session.commit()
            orders = (
                session.query(TradeOrder)
                .filter(TradeOrder.run_id == run.id)
                .order_by(TradeOrder.id.asc())
                .all()
            )
            params["builder"] = {
                "portfolio_value": portfolio_value,
                "cash_buffer_ratio": cash_buffer_ratio,
                "lot_size": lot_size,
                "order_type": order_type,
                "limit_price": limit_price,
                "created_orders": created,
            }
            params["price_map"] = price_map
            run.params = params
            run.updated_at = datetime.utcnow()
            session.commit()

        if not snapshot_map:
            symbols = sorted({order.symbol for order in orders})
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

        defaults = settings_row.risk_defaults if settings_row else {}
        risk_overrides = params.get("risk_overrides") if isinstance(params.get("risk_overrides"), dict) else {}
        risk_params = _merge_risk_params(defaults, risk_overrides)
        account_summary = fetch_account_summary(session)
        if isinstance(account_summary, dict):
            net_liq = account_summary.get("NetLiquidation")
            if net_liq is not None and not params.get("portfolio_value"):
                try:
                    portfolio_value = float(net_liq)
                except (TypeError, ValueError):
                    portfolio_value = 0.0
                if portfolio_value > 0:
                    params["portfolio_value"] = portfolio_value
                    run.params = params
                    run.updated_at = datetime.utcnow()
                    session.commit()
            cash_available = account_summary.get("cash_available")
            if cash_available is not None and "cash_available" not in risk_params:
                risk_params["cash_available"] = cash_available
            params.setdefault("cash_available", cash_available)
        params["risk_effective"] = risk_params
        max_order_notional = risk_params.get("max_order_notional")
        max_position_ratio = risk_params.get("max_position_ratio")
        max_total_notional = risk_params.get("max_total_notional")
        max_symbols = risk_params.get("max_symbols")
        min_cash_buffer_ratio = risk_params.get("min_cash_buffer_ratio")
        cash_available = risk_params.get("cash_available") or params.get("cash_available")
        portfolio_value = risk_params.get("portfolio_value") or params.get("portfolio_value")

        risk_orders = []
        for order in orders:
            price = _resolve_snapshot_price(order.symbol, snapshot_map)
            risk_orders.append(
                {
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": order.quantity,
                    "price": price or 0.0,
                }
            )
        ok, blocked_orders, reasons = evaluate_orders(
            risk_orders,
            max_order_notional=max_order_notional,
            max_position_ratio=max_position_ratio,
            portfolio_value=portfolio_value,
            max_total_notional=max_total_notional,
            max_symbols=max_symbols,
            cash_available=cash_available,
            min_cash_buffer_ratio=min_cash_buffer_ratio,
        )
        if not ok:
            run.status = "blocked"
            run.message = reasons[0] if reasons else "risk_blocked"
            params["risk_blocked"] = {
                "reasons": reasons,
                "count": len(blocked_orders),
                "risk_effective": risk_params,
            }
            run.params = params
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        run.status = "running"
        run.started_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        session.commit()

        symbols = sorted({order.symbol for order in orders})
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

        filled = 0
        cancelled = 0
        rejected = 0
        skipped = 0

        ib_settings = ensure_ib_client_id(session)
        api_mode = resolve_ib_api_mode(ib_settings)
        if not dry_run and api_mode == "ib":
            result = _execute_orders_with_ib(session, run, orders, price_map=price_map)
            if isinstance(result, dict):
                filled = int(result.get("filled") or 0)
                rejected = int(result.get("rejected") or 0)
                cancelled = int(result.get("cancelled") or 0)
            skipped = sum(1 for order in orders if order.status in {"FILLED", "CANCELED", "REJECTED"})
            if filled == 0 and rejected == 0 and cancelled == 0:
                run.status = "running"
                run.message = "submitted_ib"
                run.updated_at = datetime.utcnow()
                session.commit()
            else:
                _finalize_run_status(session, run, filled=filled, rejected=rejected, cancelled=cancelled)
                run.message = "executed_ib"
                session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=filled,
                cancelled=cancelled,
                rejected=rejected,
                skipped=skipped,
                message=run.message,
                dry_run=dry_run,
            )

        for order in orders:
            if order.status in {"FILLED", "CANCELED", "REJECTED"}:
                skipped += 1
                continue
            snapshot_item = snapshot_map.get(order.symbol) or {}
            price = _resolve_snapshot_price(order.symbol, snapshot_map)
            if price is None:
                rejected += 1
                record_guard_event(
                    session,
                    project_id=run.project_id,
                    mode=run.mode,
                    event="market_data_error",
                )
                if not dry_run:
                    update_trade_order_status(
                        session,
                        order,
                        {
                            "status": "REJECTED",
                            "params": {"reason": "price_unavailable", "source": "mock"},
                        },
                    )
                continue

            side = (order.side or "").strip().upper()
            limit_price = order.limit_price
            should_fill = True
            if (order.order_type or "").upper() == "LMT":
                if limit_price is None:
                    should_fill = False
                else:
                    should_fill = _limit_allows_fill(side, price, float(limit_price))

            if not should_fill:
                cancelled += 1
                if not dry_run:
                    update_trade_order_status(
                        session,
                        order,
                        {
                            "status": "CANCELED",
                            "params": {"reason": "limit_not_reached", "source": "mock"},
                        },
                    )
                continue

            filled += 1
            if dry_run:
                continue
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
            update_trade_order_status(
                session,
                order,
                {
                    "status": "FILLED",
                    "filled_quantity": order.quantity,
                    "avg_fill_price": price,
                    "params": {"source": "mock"},
                },
            )
            fill = TradeFill(
                order_id=order.id,
                fill_quantity=order.quantity,
                fill_price=price,
                commission=None,
                fill_time=datetime.utcnow(),
                params={"source": "mock"},
            )
            session.add(fill)
            session.commit()

        if dry_run:
            run.status = "queued"
            run.message = "dry_run_only"
            run.started_at = None
            run.updated_at = datetime.utcnow()
        else:
            if filled == 0:
                run.status = "failed"
            elif rejected or cancelled:
                run.status = "partial"
            else:
                run.status = "done"
            run.message = "executed_mock"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
        session.commit()

        return TradeExecutionResult(
            run_id=run.id,
            status=run.status,
            filled=filled,
            cancelled=cancelled,
            rejected=rejected,
            skipped=skipped,
            message=run.message,
            dry_run=dry_run,
        )
    except Exception as exc:
        if run is not None:
            run.status = "failed"
            run.message = f"execution_error:{exc}"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
        raise
    finally:
        lock.release()
        session.close()
