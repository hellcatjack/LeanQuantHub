from __future__ import annotations

from fastapi import APIRouter, HTTPException
from app.db import get_session
from app.schemas import (
    IBConnectionHeartbeat,
    IBConnectionStateOut,
    IBHealthOut,
    IBAccountSummaryOut,
    IBAccountPositionsOut,
    IBSettingsOut,
    IBSettingsUpdate,
    IBStreamStatusOut,
    IBStreamSnapshotOut,
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
from app.services.ib_account import get_account_summary, get_account_positions
from app.services.lean_bridge import read_quote, read_stream_status

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
    status = read_stream_status()
    return IBStreamStatusOut(**status)


@router.get("/stream/snapshot", response_model=IBStreamSnapshotOut)
def get_ib_stream_snapshot(symbol: str):
    if not str(symbol or "").strip():
        raise HTTPException(status_code=400, detail="symbol_required")
    payload = read_quote(symbol)
    return IBStreamSnapshotOut(**payload)
