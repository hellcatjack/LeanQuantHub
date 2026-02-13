from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.models import TradeOrder
from app.services.ib_settings import get_or_create_ib_settings
from app.services.lean_execution import apply_execution_events
from app.services.trade_orders import update_trade_order_status


_CANDIDATE_STATUSES = ("SUBMITTED", "PARTIAL", "CANCEL_REQUESTED", "CANCELED", "CANCELLED", "SKIPPED")
_COMPLETED_CANDIDATE_STATUSES = ("SUBMITTED", "PARTIAL", "CANCEL_REQUESTED")
_COMPLETED_FILLED_STATUSES = {"FILLED"}
_COMPLETED_CANCELED_STATUSES = {"CANCELED", "CANCELLED", "APICANCELLED", "PENDINGCANCEL"}
_QUERY_LOCK = threading.Lock()
_LAST_QUERY_MONO = 0.0
_COMPLETED_QUERY_LOCK = threading.Lock()
_LAST_COMPLETED_QUERY_MONO = 0.0


@dataclass(frozen=True)
class _CandidateOrder:
    order_id: int
    run_id: int | None
    ib_order_id: int
    symbol: str
    side: str
    tag: str
    status: str
    submit_source: str
    submit_status: str
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class _IBExecutionRow:
    order_id: int
    symbol: str
    side: str
    shares: float
    price: float
    exec_id: str
    time_raw: str


@dataclass(frozen=True)
class _IBCompletedOrderRow:
    order_id: int
    perm_id: int
    symbol: str
    side: str
    status: str
    completed_time_raw: str
    order_ref: str
    completed_status: str


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _normalize_side(value: object) -> str:
    side = str(value or "").strip().upper()
    if side in {"BUY", "BOT"}:
        return "BUY"
    if side in {"SELL", "SLD"}:
        return "SELL"
    return ""


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_ib_execution_time_to_iso(value: object) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d-%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        local_dt = parsed.replace(tzinfo=_local_timezone())
        return local_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_completed_status(value: object) -> str:
    text = str(value or "").strip().upper().replace(" ", "")
    if text == "PENDINGCANCEL":
        return "PENDINGCANCEL"
    if text in {"CANCELLED", "CANCELED", "APICANCELLED"}:
        return "CANCELED"
    if text == "FILLED":
        return "FILLED"
    if text == "REJECTED":
        return "REJECTED"
    return text


def _parse_ib_completed_time_to_iso(value: object) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    parts = text.split(" ")
    if len(parts) < 2:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dt_text = f"{parts[0]} {parts[1]}"
    tzinfo = _local_timezone()
    if len(parts) >= 3:
        try:
            tzinfo = ZoneInfo(parts[2])
        except Exception:
            pass
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d-%H:%M:%S"):
        try:
            parsed = datetime.strptime(dt_text, fmt)
        except ValueError:
            continue
        completed_dt = parsed.replace(tzinfo=tzinfo)
        return completed_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _collect_candidate_orders(
    session,
    *,
    limit: int,
    lookback_hours: int,
    statuses: tuple[str, ...] = _CANDIDATE_STATUSES,
) -> list[_CandidateOrder]:
    hours = max(1, int(lookback_hours))
    window_start = (datetime.utcnow() - timedelta(hours=hours)).replace(tzinfo=None)
    rows = (
        session.query(TradeOrder)
        .filter(
            TradeOrder.updated_at >= window_start,
            TradeOrder.status.in_(tuple(statuses)),
            TradeOrder.ib_order_id.isnot(None),
        )
        .order_by(TradeOrder.updated_at.desc(), TradeOrder.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    candidates: list[_CandidateOrder] = []
    for order in rows:
        side = _normalize_side(order.side)
        if side not in {"BUY", "SELL"}:
            continue
        tag = str(order.client_order_id or "").strip()
        if not tag:
            continue
        status = str(order.status or "").strip().upper()
        params = order.params if isinstance(order.params, dict) else {}
        submit_meta = params.get("submit_command") if isinstance(params.get("submit_command"), dict) else {}
        submit_source = str(submit_meta.get("source") or "").strip().lower()
        submit_status = str(submit_meta.get("status") or "").strip().lower()
        symbol = _normalize_symbol(order.symbol)
        if not symbol:
            continue
        try:
            ib_order_id = int(order.ib_order_id or 0)
        except (TypeError, ValueError):
            continue
        if ib_order_id <= 0:
            continue
        candidates.append(
            _CandidateOrder(
                order_id=int(order.id),
                run_id=int(order.run_id) if order.run_id is not None else None,
                ib_order_id=ib_order_id,
                symbol=symbol,
                side=side,
                tag=tag,
                status=status,
                submit_source=submit_source,
                submit_status=submit_status,
                created_at=_normalize_datetime(getattr(order, "created_at", None)),
                updated_at=_normalize_datetime(getattr(order, "updated_at", None)),
            )
        )
    return candidates


def _fetch_ib_executions(
    *,
    host: str,
    port: int,
    client_id: int,
    start_time_utc: datetime,
    timeout_seconds: float = 6.0,
) -> list[_IBExecutionRow]:
    # Lazy import so tests that don't install ibapi can still import this module.
    from ibapi.client import EClient
    from ibapi.execution import ExecutionFilter
    from ibapi.wrapper import EWrapper

    class _App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.ready = threading.Event()
            self.done = threading.Event()
            self.rows: list[_IBExecutionRow] = []
            self.errors: list[tuple[int, int, str]] = []

        def nextValidId(self, _order_id: int):
            self.ready.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
            self.errors.append((int(reqId), int(errorCode), str(errorString)))

        def execDetails(self, reqId, contract, execution):
            try:
                row = _IBExecutionRow(
                    order_id=int(getattr(execution, "orderId", 0) or 0),
                    symbol=_normalize_symbol(getattr(contract, "symbol", "")),
                    side=str(getattr(execution, "side", "") or "").strip(),
                    shares=float(getattr(execution, "shares", 0.0) or 0.0),
                    price=float(getattr(execution, "price", 0.0) or 0.0),
                    exec_id=str(getattr(execution, "execId", "") or "").strip(),
                    time_raw=str(getattr(execution, "time", "") or "").strip(),
                )
            except Exception:
                return
            if row.order_id <= 0 or not row.exec_id:
                return
            self.rows.append(row)

        def execDetailsEnd(self, reqId):
            self.done.set()

    app = _App()
    worker: threading.Thread | None = None
    try:
        app.connect(host, int(port), int(client_id))
        worker = threading.Thread(target=app.run, daemon=True)
        worker.start()
        if not app.ready.wait(timeout_seconds):
            raise RuntimeError("ib_backfill_connect_timeout")

        filt = ExecutionFilter()
        start_local = start_time_utc.astimezone(_local_timezone())
        filt.time = start_local.strftime("%Y%m%d %H:%M:%S")
        app.reqExecutions(7001, filt)
        app.done.wait(timeout_seconds)
        return app.rows
    finally:
        try:
            app.disconnect()
        except Exception:
            pass
        if worker is not None:
            worker.join(timeout=0.2)


def _fetch_ib_completed_orders(
    *,
    host: str,
    port: int,
    client_id: int,
    timeout_seconds: float = 6.0,
) -> list[_IBCompletedOrderRow]:
    # Lazy import so tests that don't install ibapi can still import this module.
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    class _App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.ready = threading.Event()
            self.done = threading.Event()
            self.rows: list[_IBCompletedOrderRow] = []
            self.errors: list[tuple[int, int, str]] = []

        def nextValidId(self, _order_id: int):
            self.ready.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
            self.errors.append((int(reqId), int(errorCode), str(errorString)))

        def completedOrder(self, contract, order, orderState):
            try:
                row = _IBCompletedOrderRow(
                    order_id=int(getattr(order, "orderId", 0) or 0),
                    perm_id=int(getattr(order, "permId", 0) or 0),
                    symbol=_normalize_symbol(getattr(contract, "symbol", "")),
                    side=str(getattr(order, "action", "") or "").strip(),
                    status=_normalize_completed_status(getattr(orderState, "status", "")),
                    completed_time_raw=str(getattr(orderState, "completedTime", "") or "").strip(),
                    order_ref=str(getattr(order, "orderRef", "") or "").strip(),
                    completed_status=str(getattr(orderState, "completedStatus", "") or "").strip(),
                )
            except Exception:
                return
            if row.order_id <= 0 and not row.order_ref:
                return
            self.rows.append(row)

        def completedOrdersEnd(self):
            self.done.set()

    app = _App()
    worker: threading.Thread | None = None
    try:
        app.connect(host, int(port), int(client_id))
        worker = threading.Thread(target=app.run, daemon=True)
        worker.start()
        if not app.ready.wait(timeout_seconds):
            raise RuntimeError("ib_completed_connect_timeout")
        app.reqCompletedOrders(False)
        app.done.wait(timeout_seconds)
        return app.rows
    finally:
        try:
            app.disconnect()
        except Exception:
            pass
        if worker is not None:
            worker.join(timeout=0.2)


def _build_events(candidates: list[_CandidateOrder], executions: list[_IBExecutionRow]) -> list[dict[str, Any]]:
    by_ib_order_id: dict[int, list[_IBExecutionRow]] = {}
    for row in executions:
        by_ib_order_id.setdefault(int(row.order_id), []).append(row)

    events: list[dict[str, Any]] = []
    for candidate in candidates:
        rows = by_ib_order_id.get(candidate.ib_order_id, [])
        if not rows:
            continue
        for row in rows:
            if row.symbol and row.symbol != candidate.symbol:
                continue
            side = _normalize_side(row.side)
            if side not in {"BUY", "SELL"}:
                side = candidate.side
            if side != candidate.side:
                continue
            shares_abs = abs(float(row.shares or 0.0))
            if shares_abs <= 0:
                continue
            signed_qty = shares_abs if side == "BUY" else -shares_abs
            if float(row.price or 0.0) <= 0:
                continue
            direction = "Buy" if signed_qty > 0 else "Sell"
            events.append(
                {
                    "order_id": int(candidate.ib_order_id),
                    "symbol": candidate.symbol,
                    "status": "Filled",
                    "filled": signed_qty,
                    "fill_price": float(row.price),
                    "direction": direction,
                    "time": _parse_ib_execution_time_to_iso(row.time_raw),
                    "tag": candidate.tag,
                    "exec_id": row.exec_id,
                    "source": "ib_direct_query",
                    "source_detail": "ib_req_executions",
                }
            )
    events.sort(key=lambda item: (str(item.get("time") or ""), str(item.get("exec_id") or "")))
    return events


def _terminalize_unresolved_candidates(
    session,
    *,
    candidates: list[_CandidateOrder],
    executed_order_ids: set[int],
    open_tags: set[str],
    min_age_seconds: int,
) -> int:
    if not candidates:
        return 0
    terminalized = 0
    now = datetime.now(timezone.utc)
    min_age = max(0, int(min_age_seconds))
    for candidate in candidates:
        if candidate.status not in {"SUBMITTED", "PARTIAL", "CANCEL_REQUESTED"}:
            continue
        if candidate.run_id is not None:
            continue
        # Scope to leader-submitted direct/manual orders where open-orders miss is ambiguous.
        if candidate.submit_source and candidate.submit_source != "leader_command":
            continue
        if candidate.tag and candidate.tag in open_tags:
            continue
        if int(candidate.ib_order_id) in executed_order_ids:
            continue

        ref_dt = candidate.updated_at or candidate.created_at
        if ref_dt is None:
            continue
        try:
            age_seconds = (now - ref_dt).total_seconds()
        except Exception:
            continue
        if age_seconds < float(min_age):
            continue

        order = session.get(TradeOrder, int(candidate.order_id))
        if order is None:
            continue
        current_status = str(order.status or "").strip().upper()
        if current_status not in {"SUBMITTED", "PARTIAL", "CANCEL_REQUESTED"}:
            continue
        try:
            update_trade_order_status(
                session,
                order,
                {
                    "status": "CANCELED",
                    "params": {
                        "event_source": "ib_direct_query",
                        "event_status": "CANCELED",
                        "event_time": now.isoformat().replace("+00:00", "Z"),
                        "sync_reason": "ib_backfill_missing_terminal_no_fill",
                        "ib_backfill_unresolved_seconds": round(float(age_seconds), 3),
                    },
                },
            )
        except ValueError:
            continue
        terminalized += 1
    return terminalized


def _terminalize_candidates_from_completed_orders(
    session,
    *,
    candidates: list[_CandidateOrder],
    completed_rows: list[_IBCompletedOrderRow],
) -> dict[str, int]:
    summary = {
        "terminalized": 0,
        "skipped_filled_hint": 0,
    }
    if not candidates or not completed_rows:
        return summary

    by_tag: dict[str, list[_IBCompletedOrderRow]] = {}
    by_order_id: dict[int, list[_IBCompletedOrderRow]] = {}
    for row in completed_rows:
        if row.order_ref:
            by_tag.setdefault(row.order_ref, []).append(row)
        if int(row.order_id or 0) > 0:
            by_order_id.setdefault(int(row.order_id), []).append(row)

    active_statuses = set(_COMPLETED_CANDIDATE_STATUSES)
    for candidate in candidates:
        matches: list[_IBCompletedOrderRow] = []
        if candidate.tag in by_tag:
            matches.extend(by_tag[candidate.tag])
        if candidate.ib_order_id in by_order_id:
            matches.extend(by_order_id[candidate.ib_order_id])
        if not matches:
            continue

        filtered: list[_IBCompletedOrderRow] = []
        seen: set[tuple[int, int, str, str]] = set()
        for row in matches:
            if row.symbol and row.symbol != candidate.symbol:
                continue
            row_side = _normalize_side(row.side)
            if row_side in {"BUY", "SELL"} and row_side != candidate.side:
                continue
            key = (
                int(row.order_id or 0),
                int(row.perm_id or 0),
                str(row.status or ""),
                str(row.completed_time_raw or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            filtered.append(row)
        if not filtered:
            continue

        has_filled = any(_normalize_completed_status(row.status) in _COMPLETED_FILLED_STATUSES for row in filtered)
        has_canceled = any(
            _normalize_completed_status(row.status) in _COMPLETED_CANCELED_STATUSES for row in filtered
        )
        if has_filled:
            # Same intent can have duplicate attempts (one Filled, one Cancelled). Prefer fill path.
            summary["skipped_filled_hint"] += 1
            continue
        if not has_canceled:
            continue

        order = session.get(TradeOrder, int(candidate.order_id))
        if order is None:
            continue
        current_status = str(order.status or "").strip().upper()
        if current_status not in active_statuses:
            continue

        canceled_rows = [
            row for row in filtered if _normalize_completed_status(row.status) in _COMPLETED_CANCELED_STATUSES
        ]
        if not canceled_rows:
            continue
        latest_row = max(
            canceled_rows,
            key=lambda row: (
                _parse_ib_completed_time_to_iso(row.completed_time_raw),
                int(row.perm_id or 0),
            ),
        )
        event_time = _parse_ib_completed_time_to_iso(latest_row.completed_time_raw)
        try:
            update_trade_order_status(
                session,
                order,
                {
                    "status": "CANCELED",
                    "params": {
                        "event_source": "ib_completed_orders",
                        "event_status": "CANCELED",
                        "event_time": event_time,
                        "sync_reason": "ib_completed_order_canceled",
                        "ib_completed_status": latest_row.completed_status,
                        "ib_completed_order_ref": latest_row.order_ref or candidate.tag,
                    },
                },
            )
        except ValueError:
            continue
        summary["terminalized"] += 1
    return summary


def reconcile_orders_with_ib_completed_status(
    session,
    *,
    limit: int = 1200,
    min_query_interval_seconds: int = 8,
    lookback_hours: int = 8,
) -> dict[str, int]:
    summary = {
        "candidates": 0,
        "completed_rows_fetched": 0,
        "completed_rows_matched": 0,
        "terminalized": 0,
        "skipped_filled_hint": 0,
        "throttled": 0,
        "errors": 0,
    }
    if session is None:
        return summary

    candidates = _collect_candidate_orders(
        session,
        limit=limit,
        lookback_hours=lookback_hours,
        statuses=_COMPLETED_CANDIDATE_STATUSES,
    )
    summary["candidates"] = len(candidates)
    if not candidates:
        return summary

    global _LAST_COMPLETED_QUERY_MONO
    now_mono = time.monotonic()
    with _COMPLETED_QUERY_LOCK:
        if (
            int(min_query_interval_seconds) > 0
            and _LAST_COMPLETED_QUERY_MONO > 0
            and (now_mono - _LAST_COMPLETED_QUERY_MONO) < float(min_query_interval_seconds)
        ):
            summary["throttled"] = 1
            return summary
        _LAST_COMPLETED_QUERY_MONO = now_mono

    settings_row = get_or_create_ib_settings(session)
    host = str(getattr(settings_row, "host", "") or "").strip()
    port = int(getattr(settings_row, "port", 0) or 0)
    if not host or port <= 0:
        summary["errors"] += 1
        return summary

    # Use a high transient client id so we don't conflict with long-lived bridge/strategy clients.
    client_id = 1_910_000_000 + int(time.time()) % 10_000
    try:
        completed_rows = _fetch_ib_completed_orders(
            host=host,
            port=port,
            client_id=client_id,
        )
    except Exception:
        summary["errors"] += 1
        return summary

    summary["completed_rows_fetched"] = len(completed_rows)
    tags = {candidate.tag for candidate in candidates if candidate.tag}
    order_ids = {int(candidate.ib_order_id) for candidate in candidates if int(candidate.ib_order_id or 0) > 0}
    matched_rows = [
        row
        for row in completed_rows
        if (row.order_ref and row.order_ref in tags) or (int(row.order_id or 0) in order_ids)
    ]
    summary["completed_rows_matched"] = len(matched_rows)
    apply_summary = _terminalize_candidates_from_completed_orders(
        session,
        candidates=candidates,
        completed_rows=matched_rows,
    )
    summary["terminalized"] = int(apply_summary.get("terminalized") or 0)
    summary["skipped_filled_hint"] = int(apply_summary.get("skipped_filled_hint") or 0)
    return summary


def reconcile_direct_orders_with_ib_executions(
    session,
    *,
    limit: int = 300,
    min_query_interval_seconds: int = 15,
    lookback_hours: int = 8,
    open_tags: set[str] | None = None,
    infer_canceled_missing: bool = False,
    missing_cancel_min_age_seconds: int = 120,
) -> dict[str, int]:
    summary = {
        "candidates": 0,
        "executions_fetched": 0,
        "events_built": 0,
        "processed": 0,
        "skipped_invalid_tag": 0,
        "skipped_not_found": 0,
        "canceled_inferred": 0,
        "throttled": 0,
        "errors": 0,
    }
    if session is None:
        return summary

    candidates = _collect_candidate_orders(
        session,
        limit=limit,
        lookback_hours=lookback_hours,
    )
    summary["candidates"] = len(candidates)
    if not candidates:
        return summary

    global _LAST_QUERY_MONO
    now_mono = time.monotonic()
    with _QUERY_LOCK:
        if (
            int(min_query_interval_seconds) > 0
            and _LAST_QUERY_MONO > 0
            and (now_mono - _LAST_QUERY_MONO) < float(min_query_interval_seconds)
        ):
            summary["throttled"] = 1
            return summary
        _LAST_QUERY_MONO = now_mono

    oldest_dt = min(
        (candidate.updated_at or candidate.created_at or datetime.now(timezone.utc)) for candidate in candidates
    )
    lower_bound = datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))
    start_time_utc = oldest_dt if oldest_dt > lower_bound else lower_bound
    settings_row = get_or_create_ib_settings(session)
    host = str(getattr(settings_row, "host", "") or "").strip()
    port = int(getattr(settings_row, "port", 0) or 0)
    if not host or port <= 0:
        summary["errors"] += 1
        return summary

    # Use a high transient client id so we don't conflict with long-lived bridge/strategy clients.
    client_id = 1_900_000_000 + int(time.time()) % 10_000
    try:
        executions = _fetch_ib_executions(
            host=host,
            port=port,
            client_id=client_id,
            start_time_utc=start_time_utc,
        )
    except Exception:
        summary["errors"] += 1
        return summary

    summary["executions_fetched"] = len(executions)
    events = _build_events(candidates, executions)
    summary["events_built"] = len(events)
    executed_order_ids = {int(row.order_id) for row in executions if int(row.order_id or 0) > 0}
    if events:
        apply_summary = apply_execution_events(events, session=session)
        summary["processed"] = int(apply_summary.get("processed") or 0)
        summary["skipped_invalid_tag"] = int(apply_summary.get("skipped_invalid_tag") or 0)
        summary["skipped_not_found"] = int(apply_summary.get("skipped_not_found") or 0)

    if infer_canceled_missing:
        summary["canceled_inferred"] = _terminalize_unresolved_candidates(
            session,
            candidates=candidates,
            executed_order_ids=executed_order_ids,
            open_tags=set(open_tags or set()),
            min_age_seconds=int(missing_cancel_min_age_seconds),
        )
    return summary
