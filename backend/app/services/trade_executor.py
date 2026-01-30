from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import csv
import json
import os
import re

from app.core.config import settings
from app.db import SessionLocal
from app.models import DecisionSnapshot, TradeOrder, TradeRun, TradeSettings
from pathlib import Path

from app.services.job_lock import JobLock
from app.services.trade_guard import (
    get_or_create_guard_state,
    record_guard_event,
)
from app.services.trade_order_builder import build_orders
from app.services.trade_orders import create_trade_order
from app.services.trade_risk_engine import evaluate_orders
from app.services.trade_alerts import notify_trade_alert
from app.services.ib_account import fetch_account_summary
from app.services.trade_order_intent import write_order_intent, ensure_order_intent_ids
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_bridge_status, read_quotes
from app.services.lean_execution import build_execution_config, launch_execution


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


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _bridge_connection_ok() -> bool:
    status = read_bridge_status(_resolve_bridge_root())
    state = str(status.get("status") or "").lower()
    if status.get("stale") is True:
        return False
    return state in {"ok", "connected", "running"}


def _quote_price(item: dict[str, Any]) -> float | None:
    payload = item.get("data") if isinstance(item.get("data"), dict) else item
    return _pick_price(payload if isinstance(payload, dict) else None)


def _normalize_symbol_for_filename(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", symbol.upper())
    return cleaned.strip("_")


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
        return float(close_value)
    except (OSError, ValueError, TypeError):
        return None


def _load_fallback_prices(symbols: list[str]) -> dict[str, float]:
    root = _resolve_data_root() / "curated_adjusted"
    prices: dict[str, float] = {}
    for symbol in symbols:
        path = _find_latest_price_file(root, symbol)
        if not path:
            continue
        price = _read_latest_close(path)
        if price is None or price <= 0:
            continue
        prices[symbol] = price
    return prices


def _build_price_map(symbols: list[str]) -> dict[str, float]:
    symbol_set = {symbol for symbol in symbols if symbol}
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    prices: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol not in symbol_set:
            continue
        price = _quote_price(item)
        if price is not None and price > 0:
            prices[symbol] = price
    missing = sorted(symbol_set - set(prices.keys()))
    if missing:
        prices.update(_load_fallback_prices(missing))
    return prices


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


def execute_trade_run(
    run_id: int,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> TradeExecutionResult:
    session = SessionLocal()
    lock = None
    if not dry_run:
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
        execution_source = (settings_row.execution_data_source if settings_row else "lean") or "lean"
        if execution_source.lower() != "lean":
            params = dict(run.params or {})
            params["execution_data_source"] = execution_source
            params["expected_execution_data_source"] = "lean"
            run.status = "blocked"
            run.message = "execution_data_source_mismatch"
            run.params = dict(params)
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

        if not _bridge_connection_ok():
            run.status = "blocked"
            run.message = "bridge_unavailable"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            notify_trade_alert(session, f"Trade run blocked: lean bridge unavailable (run={run.id})")
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
                run_id=run.id,
            )
            params["order_intent_path"] = intent_path
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

            symbols = sorted({item.get("symbol") for item in items if item.get("symbol")})
            price_map = _build_price_map(symbols)

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
                            run.params = dict(params)
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
                    "client_order_id_auto": True,
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
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        if not price_map:
            symbols = sorted({order.symbol for order in orders})
            price_map = _build_price_map(symbols)

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
                    run.params = dict(params)
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

        risk_bypass = bool(params.get("risk_bypass"))
        if not risk_bypass:
            risk_orders = []
            for order in orders:
                price = price_map.get(order.symbol)
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
                run.params = dict(params)
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
        else:
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        run.status = "running"
        run.started_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        session.commit()

        filled = 0
        cancelled = 0
        rejected = 0
        skipped = 0
        if dry_run:
            run.status = "done"
            run.message = "dry_run"
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

        intent_path = params.get("order_intent_path")
        if not intent_path:
            run.status = "failed"
            run.message = "order_intent_missing"
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
        ensure_order_intent_ids(intent_path, snapshot_id=run.decision_snapshot_id)

        config = build_execution_config(
            intent_path=intent_path,
            brokerage="InteractiveBrokersBrokerage",
            project_id=run.project_id,
            mode=run.mode,
        )
        config_dir = ARTIFACT_ROOT / "lean_execution"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"trade_run_{run.id}.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        launch_execution(config_path=str(config_path))
        run.status = "running"
        run.message = "submitted_lean"
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
        if lock is not None:
            lock.release()
        session.close()
