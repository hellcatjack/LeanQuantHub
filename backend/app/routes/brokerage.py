from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.core.config import settings
from app.db import get_session
from app.schemas import (
    IBConnectionHeartbeat,
    IBConnectionStateOut,
    IBHealthOut,
    IBContractCacheOut,
    IBContractRefreshOut,
    IBContractRefreshRequest,
    IBAccountSummaryOut,
    IBAccountPositionsOut,
    IBHistoryJobCreate,
    IBHistoryJobOut,
    IBHistoricalOut,
    IBHistoricalRequest,
    IBMarketHealthOut,
    IBMarketHealthRequest,
    IBMarketSnapshotOut,
    IBMarketSnapshotRequest,
    IBSettingsOut,
    IBSettingsUpdate,
    IBStreamStartRequest,
    IBStreamStatusOut,
    IBStreamSnapshotOut,
    IBBridgeStatusOut,
    IBBridgeRefreshOut,
    IBStatusOverviewOut,
)
from app.services.audit_log import record_audit
from app.services.ib_settings import (
    get_or_create_ib_settings,
    probe_ib_connection,
    update_ib_state,
)
from app.services.ib_health import build_ib_health
from app.services.ib_status_overview import build_ib_status_overview
from app.services.ib_market import (
    check_market_health,
    fetch_historical_bars,
    fetch_market_snapshots,
    refresh_contract_cache,
)
from app.services.ib_account import get_account_summary, get_account_positions
from app.services.project_symbols import collect_active_project_symbols
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_bridge_status, read_quotes
from app.services.lean_bridge_leader import ensure_lean_bridge_leader
from app.services.lean_bridge_watchdog import build_bridge_status, refresh_bridge
from app.models import IBContractCache, IBHistoryJob, LeanExecutorPool

router = APIRouter(prefix="/api/brokerage", tags=["brokerage"])


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _mask_account(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


def _fetch_lean_pool_status(session, *, mode: str) -> list[dict]:
    if session is None:
        return []
    rows = (
        session.query(LeanExecutorPool)
        .filter(LeanExecutorPool.mode == mode)
        .order_by(LeanExecutorPool.role.asc(), LeanExecutorPool.client_id.asc())
        .all()
    )
    return [
        {
            "client_id": row.client_id,
            "role": row.role,
            "status": row.status,
            "pid": row.pid,
            "last_heartbeat": row.last_heartbeat,
            "last_order_at": row.last_order_at,
            "output_dir": row.output_dir,
            "last_error": row.last_error,
        }
        for row in rows
    ]


def _pool_action_response(*, action: str, mode: str, message: str | None = None) -> dict:
    return {
        "action": action,
        "mode": mode,
        "status": "ok",
        "message": message,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/settings", response_model=IBSettingsOut)
def get_ib_settings():
    with get_session() as session:
        settings = get_or_create_ib_settings(session)
        out = IBSettingsOut.model_validate(settings, from_attributes=True)
        out.account_id = _mask_account(out.account_id)
        return out


@router.post("/settings", response_model=IBSettingsOut)
def update_ib_settings(payload: IBSettingsUpdate):
    with get_session() as session:
        settings = get_or_create_ib_settings(session)
        data = payload.model_dump(exclude_unset=True)
        if "api_mode" in data:
            value = str(data.get("api_mode") or "").strip().lower()
            if value not in {"ib", "mock"}:
                value = "ib"
            data["api_mode"] = value
        if "use_regulatory_snapshot" in data:
            data["use_regulatory_snapshot"] = bool(data.get("use_regulatory_snapshot"))
        for key, value in data.items():
            if key == "account_id" and value == "":
                value = None
            setattr(settings, key, value)
        record_audit(
            session,
            action="brokerage.settings.update",
            resource_type="ib_settings",
            resource_id=settings.id,
            detail={
                "host": settings.host,
                "port": settings.port,
                "client_id": settings.client_id,
                "mode": settings.mode,
                "market_data_type": settings.market_data_type,
                "api_mode": settings.api_mode,
                "use_regulatory_snapshot": settings.use_regulatory_snapshot,
            },
        )
        session.commit()
        session.refresh(settings)
        out = IBSettingsOut.model_validate(settings, from_attributes=True)
        out.account_id = _mask_account(out.account_id)
        return out


@router.get("/state", response_model=IBConnectionStateOut)
def get_ib_state():
    with get_session() as session:
        state = probe_ib_connection(session)
        return IBConnectionStateOut.model_validate(state, from_attributes=True)


@router.get("/health", response_model=IBHealthOut)
def get_ib_health():
    with get_session() as session:
        payload = build_ib_health(session)
        return IBHealthOut(**payload)


@router.get("/status/overview", response_model=IBStatusOverviewOut)
def get_ib_status_overview():
    with get_session() as session:
        payload = build_ib_status_overview(session)
    return IBStatusOverviewOut(**payload)


@router.get("/account/summary", response_model=IBAccountSummaryOut)
def get_ib_account_summary(mode: str = "paper", full: bool = False):
    with get_session() as session:
        payload = get_account_summary(session, mode=mode, full=full, force_refresh=False)
        return IBAccountSummaryOut(**payload)


@router.get("/account/positions", response_model=IBAccountPositionsOut)
def get_ib_account_positions(mode: str = "paper"):
    with get_session() as session:
        payload = get_account_positions(session, mode=mode, force_refresh=False)
        return IBAccountPositionsOut(**payload)


@router.post("/account/refresh", response_model=IBAccountSummaryOut)
def refresh_ib_account_summary(mode: str = "paper", full: bool = True):
    with get_session() as session:
        payload = get_account_summary(session, mode=mode, full=full, force_refresh=True)
        return IBAccountSummaryOut(**payload)


@router.post("/state/heartbeat", response_model=IBConnectionStateOut)
def heartbeat_ib_state(payload: IBConnectionHeartbeat):
    with get_session() as session:
        state = update_ib_state(
            session,
            status=payload.status,
            message=payload.message,
            heartbeat=True,
        )
        return IBConnectionStateOut.model_validate(state, from_attributes=True)


@router.post("/state/probe", response_model=IBConnectionStateOut)
def probe_ib_state():
    with get_session() as session:
        state = probe_ib_connection(session)
        return IBConnectionStateOut.model_validate(state, from_attributes=True)


@router.get("/stream/status", response_model=IBStreamStatusOut)
def get_ib_stream_status():
    bridge_status = read_bridge_status(_resolve_bridge_root())
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    subscribed = sorted(
        {
            str(item.get("symbol") or "").strip().upper()
            for item in items
            if isinstance(item, dict) and str(item.get("symbol") or "").strip()
        }
    )
    raw_status = str(bridge_status.get("status") or "unknown")
    last_heartbeat = bridge_status.get("last_heartbeat")
    last_error = bridge_status.get("last_error")
    stale = bool(bridge_status.get("stale", False))
    if stale:
        status = "degraded"
    elif raw_status.lower() in {"ok", "connected"}:
        status = "connected"
    else:
        status = raw_status
    return IBStreamStatusOut(
        status=status,
        last_heartbeat=last_heartbeat,
        subscribed_symbols=subscribed,
        ib_error_count=1 if stale else 0,
        last_error=last_error,
        market_data_type=None,
    )


@router.get("/stream/snapshot", response_model=IBStreamSnapshotOut)
def get_ib_stream_snapshot(symbol: str):
    if not str(symbol or "").strip():
        raise HTTPException(status_code=400, detail="symbol_required")
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    normalized = str(symbol or "").strip().upper()
    payload = {"symbol": normalized, "data": None, "error": "snapshot_not_found"}
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol") or "").strip().upper() != normalized:
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        payload = {"symbol": normalized, "data": data if isinstance(data, dict) else None, "error": None}
        break
    return IBStreamSnapshotOut(**payload)


@router.post("/stream/start", response_model=IBStreamStatusOut)
def start_ib_stream(payload: IBStreamStartRequest):
    return get_ib_stream_status()


@router.post("/stream/stop", response_model=IBStreamStatusOut)
def stop_ib_stream():
    return get_ib_stream_status()


@router.get("/bridge/status", response_model=IBBridgeStatusOut)
def get_bridge_status():
    status = build_bridge_status(_resolve_bridge_root())
    return IBBridgeStatusOut(**status)


@router.post("/bridge/refresh", response_model=IBBridgeRefreshOut)
def refresh_bridge_status(
    mode: str = "paper",
    reason: str = "manual",
    force: bool = False,
):
    with get_session() as session:
        status = refresh_bridge(session, mode=mode, reason=reason, force=force)
    return IBBridgeRefreshOut(bridge_status=IBBridgeStatusOut(**status))


@router.get("/contracts", response_model=list[IBContractCacheOut])
def list_ib_contracts(symbol: str | None = None, limit: int = 200):
    with get_session() as session:
        query = session.query(IBContractCache).order_by(IBContractCache.updated_at.desc())
        if symbol:
            query = query.filter(IBContractCache.symbol == symbol.strip().upper())
        rows = query.limit(max(1, min(limit, 500))).all()
        return [IBContractCacheOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("/contracts/refresh", response_model=IBContractRefreshOut)
def refresh_ib_contracts(payload: IBContractRefreshRequest):
    with get_session() as session:
        try:
            result = refresh_contract_cache(
                session,
                symbols=payload.symbols,
                sec_type=payload.sec_type,
                exchange=payload.exchange,
                currency=payload.currency,
                use_project_symbols=payload.use_project_symbols,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        record_audit(
            session,
            action="brokerage.contracts.refresh",
            resource_type="ib_contract_cache",
            resource_id=None,
            detail={
                "total": result.get("total"),
                "updated": result.get("updated"),
                "skipped": result.get("skipped"),
            },
        )
        session.commit()
        return IBContractRefreshOut(**result)


@router.post("/market/snapshot", response_model=IBMarketSnapshotOut)
def snapshot_ib_market(payload: IBMarketSnapshotRequest):
    with get_session() as session:
        try:
            items = fetch_market_snapshots(
                session,
                symbols=payload.symbols,
                store=payload.store,
                fallback_history=payload.fallback_history,
                history_duration=payload.history_duration,
                history_bar_size=payload.history_bar_size,
                history_use_rth=payload.history_use_rth,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        success = sum(1 for item in items if item.get("data") and not item.get("error"))
        return IBMarketSnapshotOut(total=len(items), success=success, items=items)


@router.post("/history", response_model=IBHistoricalOut)
def fetch_ib_history(payload: IBHistoricalRequest):
    with get_session() as session:
        try:
            result = fetch_historical_bars(
                session,
                symbol=payload.symbol,
                duration=payload.duration,
                bar_size=payload.bar_size,
                end_datetime=payload.end_datetime,
                use_rth=payload.use_rth,
                store=payload.store,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return IBHistoricalOut(**result)


@router.post("/market/health", response_model=IBMarketHealthOut)
def check_ib_market_health(payload: IBMarketHealthRequest):
    with get_session() as session:
        symbols = payload.symbols or []
        if payload.use_project_symbols and not symbols:
            symbols, _benchmarks = collect_active_project_symbols(session)
        symbols = [item for item in symbols if str(item).strip()]
        if not symbols:
            return IBMarketHealthOut(
                status="blocked",
                total=0,
                success=0,
                missing_symbols=[],
                errors=["symbols_empty"],
            )
        if len(symbols) > 200:
            return IBMarketHealthOut(
                status="blocked",
                total=len(symbols),
                success=0,
                missing_symbols=symbols,
                errors=["symbols_too_many"],
            )
        try:
            result = check_market_health(
                session,
                symbols=symbols,
                min_success_ratio=payload.min_success_ratio,
                fallback_history=payload.fallback_history,
                history_duration=payload.history_duration,
                history_bar_size=payload.history_bar_size,
                history_use_rth=payload.history_use_rth,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return IBMarketHealthOut(**result)


@router.get("/history-jobs", response_model=list[IBHistoryJobOut])
def list_ib_history_jobs(
    limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)
):
    with get_session() as session:
        jobs = (
            session.query(IBHistoryJob)
            .order_by(IBHistoryJob.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [IBHistoryJobOut.model_validate(job, from_attributes=True) for job in jobs]


@router.get("/history-jobs/{job_id}", response_model=IBHistoryJobOut)
def get_ib_history_job(job_id: int):
    with get_session() as session:
        job = session.get(IBHistoryJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return IBHistoryJobOut.model_validate(job, from_attributes=True)


@router.get("/history-jobs/{job_id}/progress")
def get_ib_history_job_progress(job_id: int):
    with get_session() as session:
        job = session.get(IBHistoryJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
    progress_path = Path(settings.artifact_root) / f"ib_history_job_{job_id}" / "progress.json"
    if not progress_path.exists():
        return {"status": job.status}
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {"status": job.status}
    if isinstance(payload, dict):
        payload.setdefault("status", job.status)
        return payload
    return {"status": job.status}


@router.post("/history-jobs", response_model=IBHistoryJobOut)
def create_ib_history_job(
    payload: IBHistoryJobCreate, background_tasks: BackgroundTasks
):
    params = payload.model_dump()
    with get_session() as session:
        job = IBHistoryJob(status="failed", message="ib_history_disabled", params=params)
        session.add(job)
        session.commit()
        session.refresh(job)
        record_audit(
            session,
            action="brokerage_history_job.create",
            resource_type="ib_history_job",
            resource_id=job.id,
            detail={"params": params},
        )
        session.commit()
    return IBHistoryJobOut.model_validate(job, from_attributes=True)


@router.post("/history-jobs/{job_id}/cancel", response_model=IBHistoryJobOut)
def cancel_ib_history_job_route(job_id: int):
    with get_session() as session:
        job = session.get(IBHistoryJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status in {"done", "failed", "cancelled"}:
            return IBHistoryJobOut.model_validate(job, from_attributes=True)
        job.status = "cancelled"
        job.message = "cancelled"
        job.updated_at = datetime.utcnow()
        session.commit()
        record_audit(
            session,
            action="brokerage_history_job.cancel",
            resource_type="ib_history_job",
            resource_id=job.id,
            detail={},
        )
        session.commit()
        session.refresh(job)
        return IBHistoryJobOut.model_validate(job, from_attributes=True)


@router.get("/lean/pool/status")
def get_lean_pool_status(mode: str = Query("paper")):
    mode = str(mode or "paper").strip().lower() or "paper"
    with get_session() as session:
        ensure_lean_bridge_leader(session, mode=mode, force=False)
        items = _fetch_lean_pool_status(session, mode=mode)
    return {"mode": mode, "count": len(items), "items": items}


@router.post("/lean/pool/restart")
def restart_lean_pool(mode: str = Query("paper")):
    mode = str(mode or "paper").strip().lower() or "paper"
    with get_session() as session:
        ensure_lean_bridge_leader(session, mode=mode, force=True)
    return _pool_action_response(action="restart", mode=mode)


@router.post("/lean/pool/leader/switch")
def switch_lean_pool_leader(mode: str = Query("paper")):
    mode = str(mode or "paper").strip().lower() or "paper"
    with get_session() as session:
        ensure_lean_bridge_leader(session, mode=mode, force=True)
    return _pool_action_response(action="leader_switch", mode=mode)


@router.post("/lean/pool/reset")
def reset_lean_pool(mode: str = Query("paper")):
    mode = str(mode or "paper").strip().lower() or "paper"
    with get_session() as session:
        ensure_lean_bridge_leader(session, mode=mode, force=True)
    return _pool_action_response(action="reset", mode=mode)
