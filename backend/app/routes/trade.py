from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import datetime, timezone
import inspect
from pathlib import Path
from threading import Event, Lock
import time

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db import get_session
from app.models import DecisionSnapshot, TradeGuardState, TradeOrder, TradeRun, TradeSettings
from app.schemas import (
    TradeOrderCreate,
    TradeOrderOut,
    TradeOrderStatusUpdate,
    TradeManualOrderCreate,
    TradeManualRunCreate,
    TradeRunCreate,
    TradeRunDetailOut,
    TradeRunExecuteOut,
    TradeRunExecuteRequest,
    TradeRunActionRequest,
    TradeRunOut,
    TradeFillDetailOut,
    TradeReceiptOut,
    TradeReceiptPageOut,
    TradeSettingsOut,
    TradeSettingsUpdate,
    TradeAutoRecoveryOut,
    TradeDirectOrderRequest,
    TradeDirectOrderOut,
    TradeGuardEvaluateOut,
    TradeGuardEvaluateRequest,
    TradeGuardStateOut,
    TradeSymbolSummaryOut,
    TradeSymbolSummaryPageOut,
)
from app.services.audit_log import record_audit
from app.services.ib_market import check_market_health
from app.services.lean_execution import ingest_execution_events
from app.services.manual_trade_execution import execute_manual_order
from app.services.trade_guard import evaluate_intraday_guard, get_or_create_guard_state
from app.services.trade_monitor import build_trade_overview
from app.services.trade_executor import execute_trade_run
from app.services.trade_direct_order import (
    submit_direct_order,
    retry_direct_order,
    reconcile_direct_submit_command_results,
)
from app.services.trade_cancel import reconcile_cancel_requested_orders, request_cancel_trade_order
from app.services.trade_orders import create_trade_order, update_trade_order_status
from app.services.trade_order_recovery import run_auto_recovery
from app.services.trade_receipts import list_trade_receipts as build_trade_receipts
from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_open_orders, read_positions
from app.services.ib_settings import get_or_create_ib_settings
from app.services.realized_pnl import compute_realized_pnl
from app.services.realized_pnl_baseline import ensure_positions_baseline
from app.services.trade_order_intent import write_order_intent_manual
from app.services import trade_executor
from app.services.trade_run_summary import build_last_update_at, build_symbol_summary, build_trade_run_detail
from app.services.trade_run_progress import update_trade_run_progress

router = APIRouter(prefix="/api/trade", tags=["trade"])
logger = logging.getLogger("uvicorn.error")
_TRADE_ORDERS_SYNC_LOCK = Lock()
_TRADE_ORDERS_DEEP_SYNC_LOCK = Lock()
_TRADE_ORDERS_LAST_DEEP_SYNC_MONO = 0.0
_TRADE_ORDERS_DEEP_SYNC_INTERVAL_SECONDS = max(
    0.0,
    float(getattr(settings, "trade_orders_deep_sync_interval_seconds", 30.0) or 30.0),
)
_TRADE_ORDERS_REALIZED_PNL_CACHE_TTL_SECONDS = max(
    0.0,
    float(getattr(settings, "trade_orders_realized_pnl_cache_ttl_seconds", 20.0) or 20.0),
)
_TRADE_ORDERS_REALIZED_PNL_FAST_CACHE_TTL_SECONDS = max(
    0.0,
    float(getattr(settings, "trade_orders_realized_pnl_fast_cache_ttl_seconds", 5.0) or 5.0),
)
_TRADE_ORDERS_RESPONSE_CACHE_TTL_SECONDS = max(
    0.0,
    float(getattr(settings, "trade_orders_response_cache_ttl_seconds", 1.0) or 1.0),
)
_TRADE_ORDERS_RESPONSE_CACHE_MAX_ENTRIES = max(
    8,
    int(getattr(settings, "trade_orders_response_cache_max_entries", 128) or 128),
)
_TRADE_ORDERS_RESPONSE_CACHE_LOCK = Lock()
_TRADE_ORDERS_RESPONSE_INFLIGHT: dict[tuple[int, int, int | None], Event] = {}


@dataclass
class _TradeOrdersResponseCacheEntry:
    expires_mono: float
    total: int
    items: list[dict]


_TRADE_ORDERS_RESPONSE_CACHE: dict[tuple[int, int, int | None], _TradeOrdersResponseCacheEntry] = {}


def _trade_orders_cache_key(limit: int, offset: int, run_id: int | None) -> tuple[int, int, int | None]:
    return int(limit), int(offset), int(run_id) if run_id is not None else None


def _prune_trade_orders_response_cache(*, now_mono: float) -> None:
    expired_keys = [key for key, entry in _TRADE_ORDERS_RESPONSE_CACHE.items() if entry.expires_mono <= now_mono]
    for key in expired_keys:
        _TRADE_ORDERS_RESPONSE_CACHE.pop(key, None)
    overflow = len(_TRADE_ORDERS_RESPONSE_CACHE) - int(_TRADE_ORDERS_RESPONSE_CACHE_MAX_ENTRIES)
    if overflow > 0:
        stale_keys = sorted(_TRADE_ORDERS_RESPONSE_CACHE.items(), key=lambda item: item[1].expires_mono)[:overflow]
        for key, _entry in stale_keys:
            _TRADE_ORDERS_RESPONSE_CACHE.pop(key, None)


def _get_trade_orders_response_cache(
    key: tuple[int, int, int | None],
) -> _TradeOrdersResponseCacheEntry | None:
    now_mono = time.perf_counter()
    with _TRADE_ORDERS_RESPONSE_CACHE_LOCK:
        entry = _TRADE_ORDERS_RESPONSE_CACHE.get(key)
        if entry is None:
            return None
        if entry.expires_mono <= now_mono:
            _TRADE_ORDERS_RESPONSE_CACHE.pop(key, None)
            return None
        return entry


def _store_trade_orders_response_cache(
    key: tuple[int, int, int | None],
    *,
    total: int,
    items: list[dict],
) -> None:
    ttl = float(_TRADE_ORDERS_RESPONSE_CACHE_TTL_SECONDS)
    if ttl <= 0:
        return
    now_mono = time.perf_counter()
    with _TRADE_ORDERS_RESPONSE_CACHE_LOCK:
        _prune_trade_orders_response_cache(now_mono=now_mono)
        _TRADE_ORDERS_RESPONSE_CACHE[key] = _TradeOrdersResponseCacheEntry(
            expires_mono=now_mono + ttl,
            total=int(total),
            items=list(items),
        )


def _acquire_trade_orders_response_inflight(key: tuple[int, int, int | None]) -> tuple[bool, Event]:
    with _TRADE_ORDERS_RESPONSE_CACHE_LOCK:
        existing = _TRADE_ORDERS_RESPONSE_INFLIGHT.get(key)
        if existing is not None:
            return False, existing
        event = Event()
        _TRADE_ORDERS_RESPONSE_INFLIGHT[key] = event
        return True, event


def _release_trade_orders_response_inflight(key: tuple[int, int, int | None], event: Event) -> None:
    with _TRADE_ORDERS_RESPONSE_CACHE_LOCK:
        current = _TRADE_ORDERS_RESPONSE_INFLIGHT.get(key)
        if current is event:
            _TRADE_ORDERS_RESPONSE_INFLIGHT.pop(key, None)
    event.set()


def _clear_trade_orders_response_cache() -> None:
    with _TRADE_ORDERS_RESPONSE_CACHE_LOCK:
        _TRADE_ORDERS_RESPONSE_CACHE.clear()
        _TRADE_ORDERS_RESPONSE_INFLIGHT.clear()


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_open_orders_payload_fresh(
    payload: dict | None,
    *,
    now: datetime | None = None,
    max_age_seconds: int = 90,
) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("stale") is True:
        return False
    refreshed_at = payload.get("refreshed_at") or payload.get("updated_at")
    refreshed_dt = _parse_iso_datetime(refreshed_at)
    if refreshed_dt is None:
        return False
    clock = now or datetime.utcnow().replace(tzinfo=timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    try:
        age_seconds = (clock.astimezone(timezone.utc) - refreshed_dt).total_seconds()
    except Exception:
        return False
    return age_seconds <= max(0, int(max_age_seconds))


def _should_run_trade_orders_deep_sync(now_mono: float) -> bool:
    interval = max(0.0, _TRADE_ORDERS_DEEP_SYNC_INTERVAL_SECONDS)
    if interval <= 0:
        return True
    with _TRADE_ORDERS_DEEP_SYNC_LOCK:
        if _TRADE_ORDERS_LAST_DEEP_SYNC_MONO <= 0:
            return True
        return (now_mono - _TRADE_ORDERS_LAST_DEEP_SYNC_MONO) >= interval


def _mark_trade_orders_deep_sync(now_mono: float | None = None) -> None:
    global _TRADE_ORDERS_LAST_DEEP_SYNC_MONO
    value = float(now_mono) if now_mono is not None else time.perf_counter()
    with _TRADE_ORDERS_DEEP_SYNC_LOCK:
        _TRADE_ORDERS_LAST_DEEP_SYNC_MONO = value


def _merge_auto_recovery(
    incoming: dict | None,
    current: dict | None = None,
) -> dict:
    defaults = {
        "new_timeout_seconds": 45,
        "max_auto_retries": 1,
        "max_price_deviation_pct": 1.5,
        "allow_replace_outside_rth": False,
        # Live execution: long-unfilled handling, used by LeanBridgeExecutionAlgorithm.
        "unfilled_timeout_seconds": 600,
        "unfilled_reprice_interval_seconds": 0,
        "unfilled_max_reprices": 0,
        "unfilled_max_price_deviation_pct": 1.5,
    }
    merged = dict(defaults)
    if isinstance(current, dict):
        merged.update(current)
    if isinstance(incoming, dict):
        merged.update(incoming)
    return merged


@router.get("/settings", response_model=TradeSettingsOut)
def get_trade_settings():
    with get_session() as session:
        settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
        if settings_row is None:
            settings_row = TradeSettings(risk_defaults={}, execution_data_source="lean")
            settings_row.auto_recovery = _merge_auto_recovery(None, None)
            session.add(settings_row)
            session.commit()
            session.refresh(settings_row)
        elif str(settings_row.execution_data_source or "").strip().lower() != "lean":
            # Best-effort migration: older deployments stored "ib" here while execution is now
            # always driven by Lean bridge. Leaving it as "ib" would block trade execution.
            settings_row.execution_data_source = "lean"
            session.commit()
            session.refresh(settings_row)
        return TradeSettingsOut.model_validate(settings_row, from_attributes=True)


@router.get("/overview")
def get_trade_overview(project_id: int, mode: str = "paper"):
    with get_session() as session:
        return build_trade_overview(session, project_id=project_id, mode=mode)


@router.post("/settings", response_model=TradeSettingsOut)
def update_trade_settings(payload: TradeSettingsUpdate):
    with get_session() as session:
        settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
        if settings_row is None:
            settings_row = TradeSettings(
                risk_defaults=payload.risk_defaults or {},
                execution_data_source="lean",
            )
            settings_row.auto_recovery = _merge_auto_recovery(payload.auto_recovery, None)
            session.add(settings_row)
        else:
            settings_row.risk_defaults = payload.risk_defaults
            # Execution must go through Lean bridge. Keep this locked to "lean" so risk settings
            # updates cannot accidentally flip the executor into a blocked state.
            settings_row.execution_data_source = "lean"
            if payload.auto_recovery is not None:
                settings_row.auto_recovery = _merge_auto_recovery(
                    payload.auto_recovery,
                    settings_row.auto_recovery if isinstance(settings_row.auto_recovery, dict) else None,
                )
        session.commit()
        session.refresh(settings_row)
        return TradeSettingsOut.model_validate(settings_row, from_attributes=True)


@router.get("/guard", response_model=TradeGuardStateOut)
def get_trade_guard_state(project_id: int, mode: str = "paper"):
    with get_session() as session:
        state = get_or_create_guard_state(session, project_id=project_id, mode=mode)
        return TradeGuardStateOut.model_validate(state, from_attributes=True)


@router.post("/guard/evaluate", response_model=TradeGuardEvaluateOut)
def evaluate_trade_guard(payload: TradeGuardEvaluateRequest):
    with get_session() as session:
        result = evaluate_intraday_guard(
            session,
            project_id=payload.project_id,
            mode=payload.mode,
            risk_params=payload.risk_params,
        )
        state = (
            session.query(TradeGuardState)
            .filter(
                TradeGuardState.project_id == payload.project_id,
                TradeGuardState.mode == payload.mode,
            )
            .order_by(TradeGuardState.id.desc())
            .first()
        )
        if state is None:
            raise HTTPException(status_code=404, detail="guard state not found")
        return TradeGuardEvaluateOut(
            state=TradeGuardStateOut.model_validate(state, from_attributes=True),
            result=result,
        )


def _build_market_symbols(orders: list[TradeOrderCreate]) -> list[str]:
    symbols = []
    for order in orders:
        symbol = str(order.symbol or "").strip().upper()
        if symbol:
            symbols.append(symbol)
    return sorted(set(symbols))


@router.get("/runs", response_model=list[TradeRunOut])
def list_trade_runs(limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)):
    with get_session() as session:
        cleaned = trade_executor.cleanup_terminal_run_processes(session, limit=20)
        if cleaned:
            session.commit()
        runs = (
            session.query(TradeRun)
            .order_by(TradeRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        updated = False
        for run in runs:
            if trade_executor.refresh_trade_run_status(session, run):
                updated = True
        if updated:
            session.commit()
        return [TradeRunOut.model_validate(run, from_attributes=True) for run in runs]


@router.get("/runs/{run_id}", response_model=TradeRunOut)
def get_trade_run(run_id: int):
    with get_session() as session:
        run = session.get(TradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return TradeRunOut.model_validate(run, from_attributes=True)


@router.get("/runs/{run_id}/detail", response_model=TradeRunDetailOut)
def get_trade_run_detail(
    run_id: int,
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with get_session() as session:
        run_row = session.get(TradeRun, run_id)
        if not run_row:
            raise HTTPException(status_code=404, detail="run not found")
        exec_output_dir = None
        # Keep run detail consistent with TWS: ingest run-scoped execution events and reconcile
        # against the latest open-orders snapshot so manual cancels show up without requiring a
        # separate /api/trade/orders poll.
        if isinstance(run_row.params, dict):
            lean_exec = run_row.params.get("lean_execution")
            if isinstance(lean_exec, dict):
                exec_output_dir = lean_exec.get("output_dir") or None
                if exec_output_dir:
                    run_events = Path(str(exec_output_dir)) / "execution_events.jsonl"
                    if run_events.exists():
                        ingest_execution_events(str(run_events), session=session)
        open_root = resolve_bridge_root()
        if exec_output_dir:
            open_root = Path(str(exec_output_dir))
        open_orders_payload = read_open_orders(open_root)
        sync_trade_orders_from_open_orders(
            session,
            open_orders_payload,
            mode=str(run_row.mode or "").strip().lower() or None,
            run_id=run_id,
            include_new=True,
        )
        reconcile_cancel_requested_orders(session, run_id=run_id)
        try:
            run, orders, fills, last_update_at = build_trade_run_detail(
                session, run_id, limit=limit, offset=offset
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if trade_executor.refresh_trade_run_status(session, run):
            session.commit()
        # Allow late reconciliation (e.g. positions-based fills after earlier low-confidence cancels)
        # to correct the run completion summary/status.
        trade_executor.recompute_trade_run_completion_summary(session, run)
        return TradeRunDetailOut(
            run=TradeRunOut.model_validate(run, from_attributes=True),
            orders=[TradeOrderOut.model_validate(order) for order in orders],
            fills=[TradeFillDetailOut.model_validate(fill) for fill in fills],
            last_update_at=last_update_at,
        )


@router.get("/runs/{run_id}/symbols", response_model=TradeSymbolSummaryPageOut)
def get_trade_run_symbols(run_id: int):
    with get_session() as session:
        run_row = session.get(TradeRun, run_id)
        if not run_row:
            raise HTTPException(status_code=404, detail="run not found")
        exec_output_dir = None
        if isinstance(run_row.params, dict):
            lean_exec = run_row.params.get("lean_execution")
            if isinstance(lean_exec, dict):
                exec_output_dir = lean_exec.get("output_dir") or None
                if exec_output_dir:
                    run_events = Path(str(exec_output_dir)) / "execution_events.jsonl"
                    if run_events.exists():
                        ingest_execution_events(str(run_events), session=session)
        open_root = resolve_bridge_root()
        if exec_output_dir:
            open_root = Path(str(exec_output_dir))
        open_orders_payload = read_open_orders(open_root)
        sync_trade_orders_from_open_orders(
            session,
            open_orders_payload,
            mode=str(run_row.mode or "").strip().lower() or None,
            run_id=run_id,
            include_new=True,
        )
        reconcile_cancel_requested_orders(session, run_id=run_id)
        trade_executor.recompute_trade_run_completion_summary(session, run_row)
        try:
            items = build_symbol_summary(session, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        last_update_at = build_last_update_at(session, run_id)
        return TradeSymbolSummaryPageOut(
            items=[TradeSymbolSummaryOut(**item) for item in items],
            last_update_at=last_update_at,
        )


@router.post("/runs", response_model=TradeRunOut)
def create_trade_run(payload: TradeRunCreate):
    with get_session() as session:
        if (payload.mode or "").lower() == "live":
            token = (payload.live_confirm_token or "").strip().upper()
            if token != "LIVE":
                raise HTTPException(status_code=403, detail="live_confirm_required")
        params = payload.model_dump(exclude={"orders"})
        orders = payload.orders or []
        snapshot_id = payload.decision_snapshot_id
        if snapshot_id is None:
            latest = (
                session.query(DecisionSnapshot)
                .filter(DecisionSnapshot.project_id == payload.project_id)
                .filter(DecisionSnapshot.status == "success")
                .order_by(DecisionSnapshot.created_at.desc())
                .first()
            )
            if latest:
                snapshot_id = latest.id
        if not orders:
            if snapshot_id is None:
                raise HTTPException(status_code=409, detail="decision_snapshot_required")
            snapshot = session.get(DecisionSnapshot, snapshot_id)
            if snapshot is None:
                raise HTTPException(status_code=404, detail="decision_snapshot_not_found")
            if str(snapshot.status or "").lower() != "success" or not snapshot.items_path:
                raise HTTPException(status_code=409, detail="decision_snapshot_not_ready")
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        existing = (
            session.query(TradeRun)
            .filter(
                TradeRun.project_id == payload.project_id,
                TradeRun.decision_snapshot_id == snapshot_id,
                TradeRun.mode == payload.mode,
                TradeRun.created_at >= day_start,
            )
            .order_by(TradeRun.created_at.desc())
            .first()
        )
        if existing:
            status = str(existing.status or "").strip().lower()
            # Idempotency guard: avoid creating duplicate *active* runs for the same
            # snapshot+mode within the same day (usually from repeated button clicks).
            # Completed runs (done/partial/failed/blocked) should allow new runs.
            if status in {"queued", "running", "stalled"}:
                out = TradeRunOut.model_validate(existing, from_attributes=True)
                out.orders_created = 0
                return out
        run = TradeRun(
            project_id=payload.project_id,
            decision_snapshot_id=snapshot_id,
            mode=payload.mode,
            status="queued",
            params=params,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        if orders and payload.require_market_health:
            symbols = _build_market_symbols(orders)
            health = check_market_health(
                session,
                symbols=symbols,
                min_success_ratio=payload.health_min_success_ratio,
                fallback_history=payload.health_fallback_history,
                history_duration=payload.health_history_duration,
                history_bar_size=payload.health_history_bar_size,
                history_use_rth=payload.health_history_use_rth,
            )
            params["market_health"] = health
            run.params = params
            if health.get("status") != "ok":
                run.status = "blocked"
                run.message = "market_health_blocked"
                run.ended_at = datetime.utcnow()
                session.commit()
                out = TradeRunOut.model_validate(run, from_attributes=True)
                out.orders_created = 0
                return out

        created = 0
        for order in orders:
            try:
                result = create_trade_order(session, order.model_dump(), run_id=run.id)
                if result.created:
                    created += 1
            except ValueError as exc:
                run.status = "failed"
                run.message = str(exc)
                run.ended_at = datetime.utcnow()
                session.commit()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        run.status = "queued"
        run.updated_at = datetime.utcnow()
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            run.status = "failed"
            run.message = "client_order_id_conflict"
            run.ended_at = datetime.utcnow()
            session.commit()
            raise HTTPException(status_code=409, detail="client_order_id_conflict")
        record_audit(
            session,
            action="trade_run.create",
            resource_type="trade_run",
            resource_id=run.id,
            detail={"orders_created": created},
        )
        session.commit()
        out = TradeRunOut.model_validate(run, from_attributes=True)
        out.orders_created = created
        return out


@router.post("/runs/{run_id}/execute", response_model=TradeRunExecuteOut)
def execute_trade_run_route(run_id: int, payload: TradeRunExecuteRequest):
    with get_session() as session:
        run = session.get(TradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        if (run.mode or "").lower() == "live":
            token = (payload.live_confirm_token or "").strip().upper()
            if token != "LIVE":
                raise HTTPException(status_code=403, detail="live_confirm_required")
    try:
        result = execute_trade_run(run_id, dry_run=payload.dry_run, force=payload.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with get_session() as session:
        record_audit(
            session,
            action="trade_run.execute",
            resource_type="trade_run",
            resource_id=run_id,
            detail={
                "status": result.status,
                "filled": result.filled,
                "cancelled": result.cancelled,
                "rejected": result.rejected,
                "skipped": result.skipped,
                "dry_run": result.dry_run,
            },
        )
        session.commit()
    return TradeRunExecuteOut(**result.__dict__)


@router.post("/runs/{run_id}/resume", response_model=TradeRunOut)
def resume_trade_run(run_id: int, payload: TradeRunActionRequest | None = None):
    with get_session() as session:
        run = session.get(TradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        if str(run.status or "").lower() != "stalled":
            raise HTTPException(status_code=409, detail="run_not_stalled")
        reason = payload.reason if payload else None
        now = datetime.utcnow()
        run.status = "running"
        run.message = "manual_resume"
        run.stalled_at = None
        run.stalled_reason = None
        run.last_progress_at = now
        run.progress_stage = "manual_resume"
        run.progress_reason = reason
        run.updated_at = now
        record_audit(
            session,
            action="trade_run.resume",
            resource_type="trade_run",
            resource_id=run.id,
            detail={"reason": reason},
        )
        session.commit()
        session.refresh(run)
        return TradeRunOut.model_validate(run, from_attributes=True)


@router.post("/runs/{run_id}/terminate", response_model=TradeRunOut)
def terminate_trade_run(run_id: int, payload: TradeRunActionRequest | None = None):
    with get_session() as session:
        run = session.get(TradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        if str(run.status or "").lower() in {"done", "partial", "failed"}:
            raise HTTPException(status_code=409, detail="run_already_completed")
        reason = payload.reason if payload else None
        now = datetime.utcnow()
        run.status = "failed"
        run.message = "manual_terminate"
        run.ended_at = now
        run.stalled_at = None
        run.stalled_reason = None
        run.last_progress_at = now
        run.progress_stage = "manual_terminate"
        run.progress_reason = reason
        run.updated_at = now
        record_audit(
            session,
            action="trade_run.terminate",
            resource_type="trade_run",
            resource_id=run.id,
            detail={"reason": reason},
        )
        session.commit()
        session.refresh(run)
        return TradeRunOut.model_validate(run, from_attributes=True)


@router.post("/runs/{run_id}/sync", response_model=TradeRunOut)
def sync_trade_run(run_id: int):
    with get_session() as session:
        run = session.get(TradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        updated = trade_executor.refresh_trade_run_status(session, run)
        recomputed = trade_executor.recompute_trade_run_completion_summary(session, run)
        if updated:
            update_trade_run_progress(session, run, "manual_sync", reason="manual_sync", commit=False)
        record_audit(
            session,
            action="trade_run.sync",
            resource_type="trade_run",
            resource_id=run.id,
            detail={"updated": updated, "recomputed": recomputed},
        )
        session.commit()
        session.refresh(run)
        return TradeRunOut.model_validate(run, from_attributes=True)


@router.post("/runs/manual", response_model=TradeRunExecuteOut)
def create_manual_trade_run(payload: TradeManualRunCreate):
    with get_session() as session:
        if (payload.mode or "").lower() == "live":
            token = (payload.live_confirm_token or "").strip().upper()
            if token != "LIVE":
                raise HTTPException(status_code=403, detail="live_confirm_required")
        run = TradeRun(
            project_id=payload.project_id,
            decision_snapshot_id=payload.decision_snapshot_id,
            mode=payload.mode,
            status="queued",
            params={"source": "manual"},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        orders = []
        created = 0
        for idx, order in enumerate(payload.orders or []):
            client_order_id = f"oi_{run.id}_{idx}"
            order_payload = order.model_dump()
            order_payload["client_order_id"] = client_order_id
            try:
                result = create_trade_order(session, order_payload, run_id=run.id)
                if result.created:
                    created += 1
            except ValueError as exc:
                run.status = "failed"
                run.message = str(exc)
                run.ended_at = datetime.utcnow()
                session.commit()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            orders.append(order_payload)
        session.commit()

        params = dict(run.params or {})
        intent_path = write_order_intent_manual(
            run_id=run.id,
            orders=orders,
            output_dir=trade_executor.ARTIFACT_ROOT / "order_intents",
        )
        params["order_intent_path"] = intent_path
        params["risk_bypass"] = True
        run.params = dict(params)
        run.updated_at = datetime.utcnow()
        session.commit()

    result = execute_trade_run(run.id, dry_run=False, force=True)
    return TradeRunExecuteOut(**result.__dict__)


@router.get("/orders", response_model=list[TradeOrderOut])
def list_trade_orders(
    response: Response = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    run_id: int | None = None,
):
    if response is None:
        response = Response()
    cache_key = _trade_orders_cache_key(limit, offset, run_id)
    cache_owner = False
    cache_event: Event | None = None
    cache_enabled = run_id is None and _TRADE_ORDERS_RESPONSE_CACHE_TTL_SECONDS > 0
    if cache_enabled:
        cached = _get_trade_orders_response_cache(cache_key)
        if cached is not None:
            response.headers["X-Total-Count"] = str(cached.total)
            return [TradeOrderOut.model_validate(item) for item in cached.items]
        cache_owner, cache_event = _acquire_trade_orders_response_inflight(cache_key)
        if not cache_owner:
            wait_timeout = max(0.05, min(1.0, float(_TRADE_ORDERS_RESPONSE_CACHE_TTL_SECONDS) * 2.0))
            cache_event.wait(timeout=wait_timeout)
            cached = _get_trade_orders_response_cache(cache_key)
            if cached is not None:
                response.headers["X-Total-Count"] = str(cached.total)
                return [TradeOrderOut.model_validate(item) for item in cached.items]
            cache_owner, cache_event = _acquire_trade_orders_response_inflight(cache_key)

    bridge_root = resolve_bridge_root()
    t0 = time.perf_counter()
    last = t0
    durations: dict[str, float] = {}

    def lap(name: str) -> None:
        nonlocal last
        now = time.perf_counter()
        durations[name] = now - last
        last = now

    try:
        with get_session() as session:
            try:
                get_or_create_ib_settings(session)
            except Exception:
                pass
            lap("settings")

            # Root-cause fix for long sync-lock hold:
            # - never run execution-event ingestion/open-orders reconciliation in request path.
            # - rely on watchdog + run/detail endpoints for state convergence.
            active_rows_count = 0
            run_ids_count = 0
            sync_mode = "watchdog"
            lap("ingest_global")
            lap("reconcile_direct_submit")
            lap("query_active")
            lap("ingest_active_runs")
            lap("ingest_active_direct")
            lap("sync_open_orders")
            query = session.query(TradeOrder).order_by(TradeOrder.id.desc())
            if run_id is not None:
                query = query.filter(TradeOrder.run_id == run_id)
            total = query.order_by(None).count()
            response.headers["X-Total-Count"] = str(total)
            lap("count")
            orders = query.offset(offset).limit(limit).all()
            lap("fetch_page")

            realized_order_totals: dict[int, float] = {}
            page_realized_symbols = {
                str(order.symbol or "").strip().upper()
                for order in orders
                if str(order.status or "").strip().upper() in {"FILLED", "PARTIAL"}
                or float(order.filled_quantity or 0.0) > 0
            }
            if page_realized_symbols:
                positions_payload = read_positions(bridge_root)
                baseline = ensure_positions_baseline(bridge_root, positions_payload)
                realized = compute_realized_pnl(
                    session,
                    baseline,
                    cache_ttl_seconds=_TRADE_ORDERS_REALIZED_PNL_CACHE_TTL_SECONDS,
                    fast_cache_ttl_seconds=_TRADE_ORDERS_REALIZED_PNL_FAST_CACHE_TTL_SECONDS,
                    symbols=page_realized_symbols,
                )
                realized_order_totals = dict(realized.order_totals)
            lap("realized_pnl")
            lap("ingest_page_events")

            total_s = time.perf_counter() - t0
            if total_s >= 0.5:
                parts = ", ".join(f"{name}={dur*1000:.0f}ms" for name, dur in durations.items())
                logger.warning(
                    "Slow list_trade_orders total=%.0fms %s active=%s runs=%s total=%s limit=%s offset=%s run_id=%s sync=%s",
                    total_s * 1000,
                    parts,
                    active_rows_count,
                    run_ids_count,
                    total,
                    limit,
                    offset,
                    run_id,
                    sync_mode,
                )
            items = [
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
                    "realized_pnl": realized_order_totals.get(order.id, 0.0),
                    "params": order.params,
                    "created_at": order.created_at,
                    "updated_at": order.updated_at,
                }
                for order in orders
            ]
            if cache_enabled and cache_owner:
                _store_trade_orders_response_cache(cache_key, total=total, items=items)
            return [TradeOrderOut.model_validate(item) for item in items]
    finally:
        if cache_enabled and cache_owner and cache_event is not None:
            _release_trade_orders_response_inflight(cache_key, cache_event)


@router.get("/runs/{run_id}/orders", response_model=list[TradeOrderOut])
def get_trade_run_orders(
    run_id: int,
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with get_session() as session:
        bridge_root = resolve_bridge_root()
        run = session.get(TradeRun, run_id)
        events_path = None
        if run is not None and isinstance(run.params, dict):
            lean_exec = run.params.get("lean_execution")
            if isinstance(lean_exec, dict) and lean_exec.get("output_dir"):
                events_path = Path(str(lean_exec["output_dir"])) / "execution_events.jsonl"
        if events_path is None:
            events_path = bridge_root / "execution_events.jsonl"
        if events_path.exists():
            try:
                ingest_params = inspect.signature(ingest_execution_events).parameters
            except (TypeError, ValueError):
                ingest_params = {}
            skip_existing = events_path == (bridge_root / "execution_events.jsonl")
            if "session" in ingest_params:
                ingest_execution_events(
                    str(events_path),
                    session=session,
                    skip_existing_on_first_read=skip_existing,
                )
            else:
                ingest_execution_events(
                    str(events_path),
                    skip_existing_on_first_read=skip_existing,
                )
        if run is not None:
            open_root = resolve_bridge_root()
            if events_path is not None:
                # Prefer run-scoped open orders snapshot for correct client-id coverage.
                open_root = events_path.parent
            open_orders_payload = read_open_orders(open_root)
            sync_trade_orders_from_open_orders(
                session,
                open_orders_payload,
                mode=str(run.mode or "").strip().lower() or None,
                run_id=run_id,
                include_new=True,
            )
            reconcile_cancel_requested_orders(session, run_id=run_id)
        if run is not None and trade_executor.refresh_trade_run_status(session, run):
            session.commit()
        if run is not None:
            trade_executor.recompute_trade_run_completion_summary(session, run)
        positions_payload = read_positions(resolve_bridge_root())
        baseline = ensure_positions_baseline(resolve_bridge_root(), positions_payload)
        realized = compute_realized_pnl(session, baseline)
        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run_id)
            .order_by(TradeOrder.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            TradeOrderOut.model_validate(
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
            for order in orders
        ]


@router.get("/receipts", response_model=TradeReceiptPageOut)
def list_trade_receipts(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mode: str = "all",
):
    mode_value = str(mode or "all").strip().lower()
    if mode_value not in {"all", "orders", "fills"}:
        raise HTTPException(status_code=422, detail="mode_invalid")
    with get_session() as session:
        # Keep monitor route lightweight: event ingestion and raw Lean log merge are handled by
        # watchdog/background pipelines. Doing both in request path can stall the backend.
        page = build_trade_receipts(
            session,
            limit=limit,
            offset=offset,
            mode=mode_value,
            ingest_lean_events=False,
            include_lean_events=False,
        )
        response.headers["X-Total-Count"] = str(page.total)
        return TradeReceiptPageOut(
            items=[TradeReceiptOut.model_validate(item, from_attributes=True) for item in page.items],
            total=page.total,
            warnings=page.warnings,
        )


@router.post("/orders/direct", response_model=TradeDirectOrderOut)
def create_direct_trade_order_route(payload: TradeDirectOrderRequest):
    with get_session() as session:
        try:
            result = submit_direct_order(session, payload.model_dump())
        except ValueError as exc:
            detail = str(exc)
            if detail == "live_confirm_required":
                raise HTTPException(status_code=403, detail=detail) from exc
            if detail in {"ib_api_mode_disabled", "ib_settings_missing", "client_id_busy"}:
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=400, detail=detail) from exc
        return result


@router.post("/orders/{order_id}/retry", response_model=TradeDirectOrderOut)
def retry_direct_trade_order(order_id: int, force: bool = False):
    with get_session() as session:
        try:
            result = retry_direct_order(session, order_id=order_id, force=force)
        except ValueError as exc:
            detail = str(exc)
            if detail == "order_not_found":
                raise HTTPException(status_code=404, detail=detail) from exc
            if detail == "order_not_retryable":
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=400, detail=detail) from exc
        return result


@router.get("/orders/{order_id}", response_model=TradeOrderOut)
def get_trade_order(order_id: int):
    with get_session() as session:
        order = session.get(TradeOrder, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        bridge_root = resolve_bridge_root()
        direct_events = bridge_root / f"direct_{order_id}" / "execution_events.jsonl"
        if direct_events.exists():
            try:
                ingest_params = inspect.signature(ingest_execution_events).parameters
            except (TypeError, ValueError):
                ingest_params = {}
            if "session" in ingest_params:
                ingest_execution_events(str(direct_events), session=session)
            else:
                ingest_execution_events(str(direct_events))
            session.refresh(order)
        return TradeOrderOut.model_validate(order, from_attributes=True)


@router.post("/orders/{order_id}/cancel", response_model=TradeOrderOut)
def cancel_trade_order_route(order_id: int):
    with get_session() as session:
        order = session.get(TradeOrder, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        try:
            order = request_cancel_trade_order(session, order=order, actor="user")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return TradeOrderOut.model_validate(order, from_attributes=True)


@router.post("/orders", response_model=TradeOrderOut)
def create_trade_order_route(payload: TradeOrderCreate):
    with get_session() as session:
        try:
            result = create_trade_order(session, payload.model_dump())
            session.commit()
            session.refresh(result.order)
            params = payload.params or {}
            source = str(params.get("source", "")).lower()
            if source == "manual":
                project_id = params.get("project_id")
                if project_id is None:
                    raise HTTPException(status_code=422, detail="project_id_required")
                mode = params.get("mode") or "paper"
                execute_manual_order(session, result.order, project_id=int(project_id), mode=str(mode))
                session.refresh(result.order)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="client_order_id_conflict") from exc
        return TradeOrderOut.model_validate(result.order, from_attributes=True)


@router.post("/orders/{order_id}/status", response_model=TradeOrderOut)
def update_trade_order_status_route(order_id: int, payload: TradeOrderStatusUpdate):
    with get_session() as session:
        order = session.get(TradeOrder, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        try:
            order = update_trade_order_status(session, order, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return TradeOrderOut.model_validate(order, from_attributes=True)


@router.post("/orders/auto-recover", response_model=TradeAutoRecoveryOut)
def auto_recover_trade_orders(limit: int = Query(200, ge=1, le=1000)):
    with get_session() as session:
        result = run_auto_recovery(session, limit=limit)
        return TradeAutoRecoveryOut(**result)
