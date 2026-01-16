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
    IBContractCacheOut,
    IBContractRefreshOut,
    IBContractRefreshRequest,
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
)
from app.services.audit_log import record_audit
from app.services.ib_settings import (
    get_or_create_ib_settings,
    probe_ib_connection,
    update_ib_state,
)
from app.services.ib_market import (
    check_market_health,
    fetch_historical_bars,
    fetch_market_snapshots,
    refresh_contract_cache,
)
from app.services.ib_history_runner import cancel_ib_history_job, run_ib_history_job
from app.services.project_symbols import collect_active_project_symbols
from app.models import IBContractCache, IBHistoryJob

router = APIRouter(prefix="/api/ib", tags=["ib"])


def _mask_account(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"


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
            action="ib.settings.update",
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
        state = update_ib_state(session, heartbeat=False)
        return IBConnectionStateOut.model_validate(state, from_attributes=True)


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
            action="ib.contracts.refresh",
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
        job = IBHistoryJob(status="queued", params=params)
        session.add(job)
        session.commit()
        session.refresh(job)
        record_audit(
            session,
            action="ib_history_job.create",
            resource_type="ib_history_job",
            resource_id=job.id,
            detail={"params": params},
        )
        session.commit()
    background_tasks.add_task(run_ib_history_job, job.id)
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
        cancel_ib_history_job(job_id)
        record_audit(
            session,
            action="ib_history_job.cancel",
            resource_type="ib_history_job",
            resource_id=job.id,
            detail={},
        )
        session.commit()
        session.refresh(job)
        return IBHistoryJobOut.model_validate(job, from_attributes=True)
