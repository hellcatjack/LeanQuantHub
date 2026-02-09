from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any
import csv
import json
import os
import re
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db import SessionLocal
from app.models import DecisionSnapshot, TradeFill, TradeOrder, TradeRun, TradeSettings
from pathlib import Path

from app.services.job_lock import JobLock
from app.services.trade_guard import (
    get_or_create_guard_state,
    record_guard_event,
)
from app.services.trade_order_builder import build_intent_orders, build_orders
from app.services.trade_orders import create_trade_order, update_trade_order_status
from app.services.trade_order_types import is_limit_like, normalize_order_type, validate_order_type
from app.services.trade_risk_engine import evaluate_orders
from app.services.trade_alerts import notify_trade_alert
from app.services.ib_account import fetch_account_summary
from app.services.trade_order_intent import write_order_intent, ensure_order_intent_ids
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import (
    parse_bridge_timestamp,
    read_bridge_status,
    read_open_orders,
    read_positions,
    read_quotes,
)
from app.services.lean_execution import (
    build_execution_config,
    ingest_execution_events,
    launch_execution_async,
)
from app.services.lean_execution_params import write_execution_params
from app.services.audit_log import record_audit
from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders
from app.services.trade_run_progress import is_market_open, is_trade_run_stalled, update_trade_run_progress


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


def _pick_quote_limit_price(
    snapshot: dict[str, Any] | None,
    *,
    side: str,
    prefer_mid: bool = False,
) -> float | None:
    if not snapshot:
        return None
    last = snapshot.get("last")
    bid = snapshot.get("bid")
    ask = snapshot.get("ask")
    try:
        last_value = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_value = None
    try:
        bid_value = float(bid) if bid is not None else None
    except (TypeError, ValueError):
        bid_value = None
    try:
        ask_value = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        ask_value = None

    if prefer_mid and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0

    if last_value is not None and last_value > 0:
        return last_value

    if (not prefer_mid) and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0

    normalized_side = str(side or "").strip().upper()
    if normalized_side == "BUY":
        if ask_value is not None and ask_value > 0:
            return ask_value
        if bid_value is not None and bid_value > 0:
            return bid_value
    if normalized_side == "SELL":
        if bid_value is not None and bid_value > 0:
            return bid_value
        if ask_value is not None and ask_value > 0:
            return ask_value
    if bid_value is not None and bid_value > 0:
        return bid_value
    if ask_value is not None and ask_value > 0:
        return ask_value
    return None


def _infer_auto_session(now: datetime) -> tuple[str, bool]:
    """Infer execution session for auto (snapshot-based) runs.

    We use settings.market_timezone/open/close to decide "rth" vs extended sessions.
    """

    current = now
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(settings.market_timezone)
    except Exception:
        zone = timezone.utc
    local = current.astimezone(zone)
    if is_market_open(current):
        return "rth", False
    # Extended hours split for better UI/logging. Defaults follow US equities convention.
    # pre: 04:00 - open, post: close - 20:00, night: others.
    open_time = time(9, 30)
    close_time = time(16, 0)
    pre_start = time(4, 0)
    post_end = time(20, 0)
    now_time = local.time()
    if local.weekday() >= 5:
        return "night", True
    if pre_start <= now_time < open_time:
        return "pre", True
    if close_time < now_time <= post_end:
        return "post", True
    return "night", True


def _build_limit_price_map(
    symbols: list[str],
    *,
    side_map: dict[str, str],
    order_type: str,
    fallback_prices: dict[str, float] | None = None,
) -> dict[str, float]:
    symbol_set = {symbol for symbol in symbols if symbol}
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    quote_map: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol not in symbol_set:
            continue
        payload = item.get("data") if isinstance(item.get("data"), dict) else item
        quote_map[symbol] = payload if isinstance(payload, dict) else {}

    prefer_mid = normalize_order_type(order_type) == "PEG_MID"
    out: dict[str, float] = {}
    for symbol in sorted(symbol_set):
        snapshot = quote_map.get(symbol)
        side = side_map.get(symbol, "")
        picked = _pick_quote_limit_price(snapshot, side=side, prefer_mid=prefer_mid)
        if picked is not None and picked > 0:
            out[symbol] = float(picked)

    if fallback_prices:
        for symbol, price in fallback_prices.items():
            if symbol in symbol_set and symbol not in out and price is not None and float(price) > 0:
                out[symbol] = float(price)

    missing = sorted(symbol_set - set(out.keys()))
    if missing:
        out.update(_load_fallback_prices(missing))
    return out


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
    # "degraded" still has a fresh heartbeat. We rely on fallback prices for sizing and let
    # the execution algorithm decide whether it can submit orders.
    return state in {"ok", "connected", "running", "degraded"}


def _resolve_lean_execution_log_path() -> Path:
    launcher_path = Path(settings.lean_launcher_path) if settings.lean_launcher_path else None
    if launcher_path:
        base = launcher_path.parent if launcher_path.is_file() else launcher_path
        candidate = base / "bin" / "Release" / "LeanBridgeExecutionAlgorithm-log.txt"
        if candidate.exists():
            return candidate
    return Path("/app/stocklean/Lean_git/Launcher/bin/Release/LeanBridgeExecutionAlgorithm-log.txt")


def _read_tail_text(path: Path, *, max_bytes: int = 400_000) -> str:
    try:
        size = path.stat().st_size
        offset = max(size - max_bytes, 0)
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _lean_no_orders_submitted(run_id: int) -> bool:
    if not run_id:
        return False
    log_path = _resolve_lean_execution_log_path()
    if not log_path.exists():
        return False
    text = _read_tail_text(log_path)
    marker = f"oi_{run_id}_"
    pos = text.rfind(marker)
    if pos < 0:
        return False
    tail = text[pos:]
    if "LEAN_BRIDGE_NO_ORDERS_SUBMITTED" in tail:
        return True
    if "Quit(): no_orders_submitted" in tail:
        return True
    return False


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


_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "INVALID", "SKIPPED"}
_CANCELLED_ORDER_STATUSES = {"CANCELED", "CANCELLED"}
_REJECTED_ORDER_STATUSES = {"REJECTED", "INVALID"}
_SKIPPED_ORDER_STATUSES = {"SKIPPED"}
_STALLED_WINDOW_MINUTES = 15


def _normalize_order_status(value: str | None) -> str:
    return str(value or "").strip().upper()


def determine_run_status(order_statuses: list[str]) -> tuple[str | None, dict[str, int]]:
    normalized = [_normalize_order_status(status) for status in order_statuses if status is not None]
    total = len(normalized)
    summary = {"total": total, "filled": 0, "cancelled": 0, "rejected": 0, "skipped": 0}
    if not normalized:
        return None, summary
    if any(status not in _TERMINAL_ORDER_STATUSES for status in normalized):
        for status in normalized:
            if status == "FILLED":
                summary["filled"] += 1
            elif status in _CANCELLED_ORDER_STATUSES:
                summary["cancelled"] += 1
            elif status in _REJECTED_ORDER_STATUSES:
                summary["rejected"] += 1
            elif status in _SKIPPED_ORDER_STATUSES:
                summary["skipped"] += 1
        return None, summary
    for status in normalized:
        if status == "FILLED":
            summary["filled"] += 1
        elif status in _CANCELLED_ORDER_STATUSES:
            summary["cancelled"] += 1
        elif status in _REJECTED_ORDER_STATUSES:
            summary["rejected"] += 1
        elif status in _SKIPPED_ORDER_STATUSES:
            summary["skipped"] += 1
    if summary["filled"] == 0 and (summary["rejected"] + summary["cancelled"] + summary["skipped"]) > 0:
        return "failed", summary
    if summary["rejected"] > 0 or summary["cancelled"] > 0 or summary["skipped"] > 0:
        return "partial", summary
    return "done", summary


def _should_skip_order_build(execution_source: str | None) -> bool:
    return str(execution_source or "").strip().lower() == "lean"


def _build_positions_map(positions_payload: dict | None) -> dict[str, dict[str, float | None]]:
    if not isinstance(positions_payload, dict):
        return {}
    items = positions_payload.get("items") if isinstance(positions_payload.get("items"), list) else []
    positions: dict[str, dict[str, float | None]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        quantity_value = item.get("quantity")
        if quantity_value is None:
            quantity_value = item.get("position")
        if quantity_value is None:
            continue
        try:
            quantity = float(quantity_value)
        except (TypeError, ValueError):
            continue
        avg_cost_value = item.get("avg_cost")
        avg_cost = None
        if avg_cost_value is not None:
            try:
                avg_cost = float(avg_cost_value)
            except (TypeError, ValueError):
                avg_cost = None
        positions[symbol] = {"quantity": quantity, "avg_cost": avg_cost}
    return positions


def _load_order_intent_items(path: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _extract_intent_symbols(items: list[dict[str, Any]]) -> list[str]:
    symbols = []
    seen = set()
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _build_sized_qty_map_from_intent(
    intent_path: str,
    *,
    price_map: dict[str, float],
    portfolio_value: float,
    cash_buffer_ratio: float,
    lot_size: int,
    min_qty: int,
) -> dict[tuple[str, str], int]:
    items = _load_order_intent_items(intent_path)
    if not items:
        return {}
    sized = build_orders(
        items,
        price_map=price_map,
        portfolio_value=portfolio_value,
        cash_buffer_ratio=cash_buffer_ratio,
        lot_size=lot_size,
        order_type="MKT",
        limit_price=None,
        min_qty=min_qty,
    )
    out: dict[tuple[str, str], int] = {}
    for draft in sized:
        symbol = str(draft.get("symbol") or "").strip().upper()
        side = str(draft.get("side") or "").strip().upper()
        qty = draft.get("quantity")
        if not symbol or not side:
            continue
        try:
            qty_value = int(qty)
        except (TypeError, ValueError):
            continue
        if qty_value <= 0:
            continue
        out[(symbol, side)] = qty_value
    return out


def enforce_intent_order_match(
    session,
    run: TradeRun,
    orders: list[TradeOrder],
    intent_path: str,
) -> bool:
    if not intent_path:
        return True
    items = _load_order_intent_items(intent_path)
    expected_symbols = _extract_intent_symbols(items)
    if not expected_symbols:
        return True
    created_symbols = sorted({str(order.symbol or "").strip().upper() for order in orders if order.symbol})
    expected_set = set(expected_symbols)
    created_set = set(created_symbols)
    missing = sorted(expected_set - created_set)
    extra = sorted(created_set - expected_set)
    if not missing and not extra:
        return True
    params = dict(run.params or {})
    params["intent_order_mismatch"] = {
        "intent_path": intent_path,
        "expected_symbols": sorted(expected_set),
        "created_symbols": created_symbols,
        "missing_symbols": missing,
        "extra_symbols": extra,
    }
    run.params = params
    run.message = "intent_order_mismatch"
    record_audit(
        session,
        action="trade_run.intent_order_mismatch",
        resource_type="trade_run",
        resource_id=run.id,
        detail=params["intent_order_mismatch"],
    )
    force_close_run(session, run, reason="intent_order_mismatch")
    return False


def _extract_open_tags(open_orders_payload: dict | None) -> set[str]:
    if not isinstance(open_orders_payload, dict):
        return set()
    items = open_orders_payload.get("items") if isinstance(open_orders_payload.get("items"), list) else []
    tags: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").strip()
        if tag:
            tags.add(tag)
    return tags


def _load_positions_baseline(run: TradeRun | None) -> dict[str, float]:
    if run is None or not isinstance(run.params, dict):
        return {}
    baseline = run.params.get("positions_baseline")
    if not isinstance(baseline, dict):
        return {}
    items = baseline.get("items") if isinstance(baseline.get("items"), list) else []
    out: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            qty = float(item.get("quantity") or 0.0)
        except (TypeError, ValueError):
            qty = 0.0
        out[symbol] = qty
    return out


def reconcile_run_with_positions(
    session,
    run: TradeRun,
    positions_payload: dict | None,
    *,
    open_tags: set[str] | None = None,
) -> dict[str, int]:
    summary = {"checked": 0, "reconciled": 0, "skipped": 0}
    if run is None or not isinstance(positions_payload, dict):
        return summary
    if positions_payload.get("stale") is True:
        return summary
    baseline = _load_positions_baseline(run)
    if not baseline:
        # Without a pre-run baseline we can't safely infer fills from holdings (would treat
        # already-held positions as filled orders).
        return summary
    positions = _build_positions_map(positions_payload)
    if not positions:
        return summary
    orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
    for order in orders:
        status = _normalize_order_status(order.status)
        if status in _TERMINAL_ORDER_STATUSES:
            continue
        summary["checked"] += 1
        tag = str(order.client_order_id or "").strip()
        if open_tags and tag and tag in open_tags:
            # Still present in IB open orders, so do not infer terminal fills from holdings yet.
            summary["skipped"] += 1
            continue
        pos = positions.get(str(order.symbol or "").strip().upper())
        if not pos:
            summary["skipped"] += 1
            continue
        pos_qty = float(pos.get("quantity") or 0.0)
        symbol_key = str(order.symbol or "").strip().upper()
        base_qty = float(baseline.get(symbol_key, 0.0))

        side = str(order.side or "").strip().upper()
        if side == "BUY":
            delta = pos_qty - base_qty
        elif side == "SELL":
            delta = base_qty - pos_qty
        else:
            summary["skipped"] += 1
            continue
        if delta <= 0:
            summary["skipped"] += 1
            continue
        target_filled = min(float(order.quantity), float(delta))
        prev_filled = float(order.filled_quantity or 0.0)
        if target_filled <= prev_filled + 1e-6:
            summary["skipped"] += 1
            continue
        incremental = target_filled - prev_filled

        # Idempotency: exec_id is deterministic for a given reconciled filled-quantity watermark.
        watermark = int(round(target_filled * 1_000_000))
        exec_id = f"positions_reconcile:{order.id}:{watermark}"
        if (
            session.query(TradeFill)
            .filter(TradeFill.order_id == order.id, TradeFill.exec_id == exec_id)
            .first()
            is not None
        ):
            summary["skipped"] += 1
            continue
        fill_price = pos.get("avg_cost")
        if not fill_price or float(fill_price) <= 0:
            fallback = order.avg_fill_price or order.limit_price
            if fallback is not None:
                fill_price = float(fallback)
        if not fill_price or float(fill_price) <= 0:
            summary["skipped"] += 1
            continue
        current_status = _normalize_order_status(order.status)
        if current_status == "NEW":
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
        total_new = target_filled
        avg_prev = float(order.avg_fill_price or 0.0)
        avg_new = (avg_prev * prev_filled + float(fill_price) * incremental) / total_new
        target_status = "PARTIAL" if total_new + 1e-6 < float(order.quantity) else "FILLED"
        update_trade_order_status(
            session,
            order,
            {
                "status": target_status,
                "filled_quantity": total_new,
                "avg_fill_price": avg_new,
                "params": {
                    "reconcile_source": "positions",
                    "baseline_quantity": base_qty,
                    "current_position_quantity": pos_qty,
                },
            },
        )
        fill = TradeFill(
            order_id=order.id,
            exec_id=exec_id,
            fill_quantity=float(incremental),
            fill_price=float(fill_price),
            commission=None,
            fill_time=datetime.utcnow(),
            params={
                "source": "positions_reconcile",
                "baseline_quantity": base_qty,
                "current_position_quantity": pos_qty,
            },
        )
        session.add(fill)
        session.commit()
        summary["reconciled"] += 1
    return summary


def force_close_run(session, run: TradeRun, *, reason: str | None = None) -> dict[str, int]:
    summary = {"total": 0, "filled": 0, "cancelled": 0, "rejected": 0}
    if run is None:
        return summary
    orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
    for order in orders:
        status = _normalize_order_status(order.status)
        summary["total"] += 1
        if status == "FILLED":
            summary["filled"] += 1
            continue
        if status in _REJECTED_ORDER_STATUSES:
            summary["rejected"] += 1
            continue
        if status in _TERMINAL_ORDER_STATUSES:
            summary["cancelled"] += 1
            continue
        if status == "NEW":
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
        update_trade_order_status(session, order, {"status": "CANCELED"})
        summary["cancelled"] += 1
    now = datetime.utcnow()
    run.status = "failed"
    run.ended_at = now
    run.updated_at = now
    run.stalled_at = None
    run.stalled_reason = None
    params = dict(run.params or {})
    params["completion_summary"] = summary
    params["force_closed"] = True
    if reason:
        params["force_close_reason"] = reason
    run.params = params
    if not run.message or run.message in {"submitted_lean", "stalled"}:
        run.message = "force_closed"
    session.commit()
    record_audit(
        session,
        action="trade_run.force_closed",
        resource_type="trade_run",
        resource_id=run.id,
        detail={
            "reason": reason,
            "summary": summary,
        },
    )
    return summary


def refresh_trade_run_status(session, run: TradeRun) -> bool:
    active_status = str(run.status or "").lower()
    if active_status not in {"running", "stalled"}:
        return False
    open_orders_payload = read_open_orders(_resolve_bridge_root())
    open_tags = _extract_open_tags(open_orders_payload)
    # Ingest per-run execution events if available.
    exec_output_dir = None
    if isinstance(run.params, dict):
        lean_exec = run.params.get("lean_execution")
        if isinstance(lean_exec, dict):
            exec_output_dir = lean_exec.get("output_dir") or None
    if exec_output_dir:
        events_path = Path(str(exec_output_dir)) / "execution_events.jsonl"
        if events_path.exists():
            ingest_execution_events(str(events_path), session=session)
    # Avoid prematurely cancelling newly-created orders: if the open-orders snapshot is older than the
    # Lean execution submission timestamp, it can't include those orders yet.
    submitted_at = None
    if isinstance(run.params, dict):
        lean_exec = run.params.get("lean_execution")
        if isinstance(lean_exec, dict):
            submitted_at = lean_exec.get("submitted_at")
    submitted_dt = parse_bridge_timestamp({"submitted_at": submitted_at}, ["submitted_at"])
    open_refreshed_dt = parse_bridge_timestamp(open_orders_payload, ["refreshed_at", "updated_at"])
    if not (submitted_dt and open_refreshed_dt and open_refreshed_dt < submitted_dt):
        include_new = False
        if submitted_dt and open_refreshed_dt:
            try:
                include_new = (open_refreshed_dt - submitted_dt).total_seconds() >= 5
            except Exception:
                include_new = False
        sync_trade_orders_from_open_orders(
            session,
            open_orders_payload,
            mode=run.mode,
            run_id=run.id,
            include_new=include_new,
        )
    positions_payload = read_positions(_resolve_bridge_root())
    reconcile_run_with_positions(session, run, positions_payload, open_tags=open_tags)
    if _lean_no_orders_submitted(run.id):
        now = datetime.utcnow()
        cancelled = 0
        filled = 0
        held_symbols: list[str] = []
        positions_map = _build_positions_map(positions_payload)
        baseline = _load_positions_baseline(run)
        if not baseline and positions_map:
            # When Lean exits with "no orders submitted", it implies positions didn't change.
            # If we don't have a pre-run baseline (older runs/tests), treat current holdings as baseline
            # for the purpose of detecting already-held targets.
            baseline = {symbol: float(item.get("quantity") or 0.0) for symbol, item in positions_map.items()}
        update_trade_run_progress(session, run, "no_orders_submitted", reason="lean_execution", commit=True)
        for order in (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        ):
            status = str(order.status or "").strip().upper()
            if isinstance(order.params, dict) and order.params.get("already_held") is True:
                symbol = str(order.symbol or "").strip().upper()
                if symbol:
                    held_symbols.append(symbol)
            if status in {"NEW", "SUBMITTED", "PARTIAL"}:
                symbol_key = str(order.symbol or "").strip().upper()
                side = str(order.side or "").strip().upper()
                base_qty = float(baseline.get(symbol_key, 0.0))
                qty = float(order.quantity or 0.0)
                if side == "BUY" and qty > 0 and base_qty >= qty - 1e-6:
                    fill_price = None
                    pos = positions_map.get(symbol_key) or {}
                    avg_cost = pos.get("avg_cost")
                    if avg_cost is not None:
                        try:
                            avg_cost_value = float(avg_cost)
                        except (TypeError, ValueError):
                            avg_cost_value = None
                        if avg_cost_value is not None and avg_cost_value > 0:
                            fill_price = float(avg_cost_value)
                    if fill_price is None:
                        fallback = order.avg_fill_price or order.limit_price
                        if fallback is not None:
                            try:
                                fallback_value = float(fallback)
                            except (TypeError, ValueError):
                                fallback_value = None
                            if fallback_value is not None and fallback_value > 0:
                                fill_price = float(fallback_value)
                    try:
                        if status == "NEW":
                            update_trade_order_status(
                                session,
                                order,
                                {"status": "SUBMITTED", "params": {"already_held": True}},
                            )
                        update_trade_order_status(
                            session,
                            order,
                            {
                                "status": "FILLED",
                                "filled_quantity": qty,
                                "avg_fill_price": fill_price,
                                "params": {"already_held": True},
                            },
                        )
                    except ValueError:
                        pass
                    else:
                        filled += 1
                        if symbol_key:
                            held_symbols.append(symbol_key)
                        continue
                try:
                    update_trade_order_status(
                        session,
                        order,
                        {"status": "CANCELED", "params": {"cancel_reason": "no_orders_submitted"}},
                    )
                except ValueError:
                    continue
                cancelled += 1
        run.status = "failed"
        run.message = "no_orders_submitted"
        run.ended_at = now
        run.updated_at = now
        run.stalled_at = None
        run.stalled_reason = None
        params = dict(run.params or {})
        params["completion_summary"] = {
            "filled": filled,
            "cancelled": cancelled,
            "rejected": 0,
            "skipped": 0,
            "no_orders_submitted": True,
        }
        params["no_orders_submitted"] = True
        if held_symbols:
            params["already_held_orders"] = sorted(set(held_symbols))
        run.params = params
        session.commit()
        record_audit(
            session,
            action="trade_run.no_orders_submitted",
            resource_type="trade_run",
            resource_id=run.id,
            detail={"cancelled": cancelled},
        )
        return True
    statuses = [
        row[0]
        for row in session.query(TradeOrder.status).filter(TradeOrder.run_id == run.id).all()
    ]
    status, summary = determine_run_status(statuses)
    if status is None:
        if active_status != "running":
            return False
        now = datetime.utcnow()
        trading_open = is_market_open(now)
        if not is_trade_run_stalled(
            run,
            now,
            window_minutes=_STALLED_WINDOW_MINUTES,
            trading_open=trading_open,
        ):
            return False
        run.status = "stalled"
        run.stalled_at = now
        run.stalled_reason = f"no_progress_{_STALLED_WINDOW_MINUTES}m"
        run.updated_at = now
        if not run.message or run.message == "submitted_lean":
            run.message = "stalled"
        record_audit(
            session,
            action="trade_run.stalled",
            resource_type="trade_run",
            resource_id=run.id,
            detail={
                "stage": run.progress_stage,
                "last_progress_at": run.last_progress_at.isoformat() if run.last_progress_at else None,
                "reason": run.stalled_reason,
            },
        )
        return True
    run.status = status
    run.ended_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    run.stalled_at = None
    run.stalled_reason = None
    params = dict(run.params or {})
    params["completion_summary"] = summary
    run.params = params
    if not run.message or run.message == "submitted_lean":
        run.message = "orders_complete"
    return True


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
        skip_build = _should_skip_order_build(execution_source)
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

            symbols = sorted({item.get("symbol") for item in items if item.get("symbol")})
            price_map = _build_price_map(symbols)

            now = datetime.utcnow()
            session_value = str(
                params.get("session")
                or params.get("execution_session")
                or params.get("trading_session")
                or ""
            ).strip().lower()
            allow_outside = params.get("allow_outside_rth")
            if allow_outside is None:
                allow_outside = params.get("outside_rth")
            extended = {
                "pre",
                "premarket",
                "pre_market",
                "post",
                "after",
                "afterhours",
                "after_hours",
                "night",
                "overnight",
            }
            if allow_outside is None and session_value:
                allow_outside = session_value in extended
            if not session_value or allow_outside is None:
                inferred_session, inferred_outside = _infer_auto_session(now)
                if not session_value:
                    session_value = inferred_session
                if allow_outside is None:
                    allow_outside = inferred_outside

            order_type_raw = params.get("order_type")
            if order_type_raw:
                order_type = validate_order_type(order_type_raw)
            else:
                order_type = "ADAPTIVE_LMT" if session_value == "rth" else "LMT"
            params["order_type"] = order_type
            params.setdefault("execution_session", session_value)
            params.setdefault("allow_outside_rth", bool(allow_outside))

            side_map: dict[str, str] = {}
            for item in items:
                symbol = str(item.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                try:
                    weight = float(item.get("weight") or 0.0)
                except (TypeError, ValueError):
                    weight = 0.0
                side_map[symbol] = "BUY" if weight >= 0 else "SELL"

            limit_price_map: dict[str, float] | None = None
            if is_limit_like(order_type):
                limit_price_map = _build_limit_price_map(
                    symbols,
                    side_map=side_map,
                    order_type=order_type,
                    fallback_prices=price_map,
                )

            intent_path = write_order_intent(
                session,
                snapshot_id=run.decision_snapshot_id,
                items=items,
                output_dir=ARTIFACT_ROOT / "order_intents",
                run_id=run.id,
                order_type=order_type,
                limit_price_map=limit_price_map,
                outside_rth=bool(allow_outside),
                execution_session=session_value,
            )
            params["order_intent_path"] = intent_path
            execution_params = {
                "min_qty": int(params.get("min_qty") or 1),
                "lot_size": int(params.get("lot_size") or 1),
                "cash_buffer_ratio": float(params.get("cash_buffer_ratio") or 0.0),
                "fee_bps": float(params.get("fee_bps") or 0.0),
                "slippage_open_bps": float(params.get("slippage_open_bps") or 0.0),
                "slippage_close_bps": float(params.get("slippage_close_bps") or 0.0),
                "risk_overrides": params.get("risk_overrides") or {},
            }
            params["execution_params_path"] = write_execution_params(
                output_dir=ARTIFACT_ROOT / "order_intents",
                run_id=run.id,
                params=execution_params,
            )
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

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
            cash_buffer_ratio = float(params.get("cash_buffer_ratio") or 0.0)
            lot_size = int(params.get("lot_size") or 1)
            order_type = validate_order_type(params.get("order_type") or "MKT")
            limit_price = params.get("limit_price")
            min_qty = int(params.get("min_qty") or 1)
            if not skip_build and portfolio_value <= 0:
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
            if skip_build:
                draft_orders = build_intent_orders(
                    items,
                    order_type=order_type,
                    limit_price_map=limit_price_map,
                )
            else:
                draft_orders = build_orders(
                    items,
                    price_map=price_map,
                    portfolio_value=portfolio_value,
                    cash_buffer_ratio=cash_buffer_ratio,
                    lot_size=lot_size,
                    order_type=order_type,
                    limit_price=limit_price,
                    min_qty=min_qty,
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

            intent_id_map: dict[tuple[str, str], str] = {}
            if skip_build and intent_path:
                for intent_item in _load_order_intent_items(intent_path):
                    intent_id = str(intent_item.get("order_intent_id") or "").strip()
                    symbol = str(intent_item.get("symbol") or "").strip().upper()
                    if not intent_id or not symbol:
                        continue
                    try:
                        weight = float(intent_item.get("weight") or 0.0)
                    except (TypeError, ValueError):
                        weight = 0.0
                    side = "BUY" if weight >= 0 else "SELL"
                    intent_id_map[(symbol, side)] = intent_id

            created = 0
            for draft in draft_orders:
                symbol_value = str(draft.get("symbol") or "").strip().upper()
                side_value = str(draft.get("side") or "").strip().upper()
                if skip_build and symbol_value and side_value:
                    client_order_id = intent_id_map.pop((symbol_value, side_value), None)
                else:
                    client_order_id = None
                if not client_order_id:
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
                if skip_build:
                    payload["params"]["intent_only"] = True
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
            if not skip_build:
                params["builder"] = {
                    "portfolio_value": portfolio_value,
                    "cash_buffer_ratio": cash_buffer_ratio,
                    "lot_size": lot_size,
                    "order_type": order_type,
                    "limit_price": limit_price,
                    "min_qty": min_qty,
                    "rounding": "ceil",
                    "created_orders": created,
                }
            params["price_map"] = price_map
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        intent_path = params.get("order_intent_path")
        if intent_path:
            if not enforce_intent_order_match(session, run, orders, intent_path):
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
            intent_path = params.get("order_intent_path")
            cash_buffer_ratio = float(params.get("cash_buffer_ratio") or 0.0)
            lot_size = int(params.get("lot_size") or 1)
            min_qty = int(params.get("min_qty") or 1)
            notional_limits_enabled = any(
                value is not None
                for value in (
                    max_order_notional,
                    max_position_ratio,
                    max_total_notional,
                )
            )
            if skip_build and intent_path:
                # In lean execution mode, orders may be created as "intent only" drafts with
                # quantity=0. This breaks notional-based risk checks. We size the draft orders
                # from intent weights when portfolio_value and prices are available.
                needs_sizing = any(float(order.quantity or 0.0) <= 0 for order in orders)
                pv_value = None
                if portfolio_value not in (None, ""):
                    try:
                        pv_value = float(portfolio_value)
                    except (TypeError, ValueError):
                        pv_value = None
                if needs_sizing and notional_limits_enabled and (pv_value is None or pv_value <= 0):
                    run.status = "blocked"
                    run.message = "risk_portfolio_value_required"
                    params["risk_blocked"] = {
                        "reasons": ["risk_portfolio_value_required"],
                        "count": len(orders),
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
                if needs_sizing and pv_value and pv_value > 0:
                    size_map = _build_sized_qty_map_from_intent(
                        intent_path,
                        price_map=price_map,
                        portfolio_value=pv_value,
                        cash_buffer_ratio=cash_buffer_ratio,
                        lot_size=lot_size,
                        min_qty=min_qty,
                    )
                    sized = 0
                    missing: list[str] = []
                    for order in orders:
                        if float(order.quantity or 0.0) > 0:
                            continue
                        symbol = str(order.symbol or "").strip().upper()
                        side = str(order.side or "").strip().upper()
                        if not symbol or not side:
                            continue
                        qty_value = size_map.get((symbol, side))
                        if qty_value is None:
                            missing.append(symbol)
                            continue
                        order.quantity = float(qty_value)
                        sized += 1
                    if sized:
                        session.commit()
                    if notional_limits_enabled and any(float(order.quantity or 0.0) <= 0 for order in orders):
                        run.status = "blocked"
                        run.message = "risk_sizing_incomplete"
                        params["risk_blocked"] = {
                            "reasons": ["risk_sizing_incomplete"],
                            "count": len(orders),
                            "missing_symbols": sorted(set(missing))[:50],
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
        update_trade_run_progress(session, run, "run_started", reason="execution_start", commit=True)

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

        if not params.get("execution_params_path"):
            execution_params = {
                "min_qty": int(params.get("min_qty") or 1),
                "lot_size": int(params.get("lot_size") or 1),
                "cash_buffer_ratio": float(params.get("cash_buffer_ratio") or 0.0),
                "fee_bps": float(params.get("fee_bps") or 0.0),
                "slippage_open_bps": float(params.get("slippage_open_bps") or 0.0),
                "slippage_close_bps": float(params.get("slippage_close_bps") or 0.0),
                "risk_overrides": params.get("risk_overrides") or {},
            }
            params["execution_params_path"] = write_execution_params(
                output_dir=ARTIFACT_ROOT / "order_intents",
                run_id=run.id,
                params=execution_params,
            )
            run.params = dict(params)
            run.updated_at = datetime.utcnow()
            session.commit()

        # Record a pre-run positions baseline so holdings-based reconciliation can infer fills
        # without treating already-held positions as executed orders.
        if not params.get("positions_baseline"):
            symbols = sorted({str(order.symbol or "").strip().upper() for order in orders if order.symbol})
            positions_payload = read_positions(_resolve_bridge_root())
            if isinstance(positions_payload, dict) and positions_payload.get("stale") is not True and symbols:
                pos_map = _build_positions_map(positions_payload)
                baseline_items = []
                for symbol in symbols:
                    try:
                        qty = float((pos_map.get(symbol) or {}).get("quantity") or 0.0)
                    except (TypeError, ValueError):
                        qty = 0.0
                    baseline_items.append({"symbol": symbol, "quantity": qty})
                params["positions_baseline"] = {
                    "refreshed_at": positions_payload.get("refreshed_at") or positions_payload.get("updated_at"),
                    "items": baseline_items,
                }
                run.params = dict(params)
                run.updated_at = datetime.utcnow()
                session.commit()

        exec_output_dir = ARTIFACT_ROOT / "lean_bridge_runs" / f"run_{run.id}"
        config = build_execution_config(
            intent_path=intent_path,
            brokerage="InteractiveBrokersBrokerage",
            project_id=run.project_id,
            mode=run.mode,
            params_path=params.get("execution_params_path"),
            lean_bridge_output_dir=str(exec_output_dir),
        )
        config_dir = ARTIFACT_ROOT / "lean_execution"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"trade_run_{run.id}.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        pid = launch_execution_async(config_path=str(config_path))
        params.setdefault("lean_execution", {})
        if isinstance(params.get("lean_execution"), dict):
            params["lean_execution"].update(
                {
                    "config_path": str(config_path),
                    "pid": pid,
                    "output_dir": str(exec_output_dir),
                    "submitted_at": datetime.utcnow().isoformat() + "Z",
                }
            )
        run.params = dict(params)
        run.updated_at = datetime.utcnow()
        session.commit()
        run.status = "running"
        run.message = "submitted_lean"
        run.updated_at = datetime.utcnow()
        session.commit()
        update_trade_run_progress(session, run, "submitted_lean", reason="lean_execution", commit=True)

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
