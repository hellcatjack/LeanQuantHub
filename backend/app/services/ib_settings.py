from __future__ import annotations

import os
import socket
from datetime import datetime

from app.models import IBConnectionState, IBSettings
from app.core.config import settings
from app.services.lean_bridge_watchdog import ensure_lean_bridge_live
from app.services.lean_bridge_reader import read_bridge_status as _read_bridge_status
from app.services.lean_bridge_paths import resolve_bridge_root


MAX_CLIENT_ID = 2_147_483_647


def derive_client_id(*, project_id: int, mode: str) -> int:
    base = settings.ib_client_id_base
    live_offset = settings.ib_client_id_live_offset
    pid = abs(int(project_id))
    cid = base + pid + (live_offset if str(mode).lower() == "live" else 0)
    return cid if cid <= MAX_CLIENT_ID else base


def _resolve_default_settings() -> dict[str, object]:
    host = (os.getenv("IB_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int((os.getenv("IB_PORT") or "7497").strip() or 7497)
    client_id = int((os.getenv("IB_CLIENT_ID") or "101").strip() or 101)
    account_id = (os.getenv("IB_ACCOUNT") or "").strip() or None
    mode = (os.getenv("IB_MODE") or "paper").strip() or "paper"
    market_data_type = (os.getenv("IB_MARKET_DATA_TYPE") or "realtime").strip() or "realtime"
    api_mode = (os.getenv("IB_API_MODE") or "ib").strip() or "ib"
    regulatory_raw = (os.getenv("IB_REGULATORY_SNAPSHOT") or "").strip().lower()
    use_regulatory_snapshot = regulatory_raw in {"1", "true", "yes", "y", "on"}
    return {
        "host": host,
        "port": port,
        "client_id": client_id,
        "account_id": account_id,
        "mode": mode,
        "market_data_type": market_data_type,
        "api_mode": api_mode,
        "use_regulatory_snapshot": use_regulatory_snapshot,
    }


def get_or_create_ib_settings(session) -> IBSettings:
    row = session.query(IBSettings).first()
    if row:
        return row
    defaults = _resolve_default_settings()
    row = IBSettings(**defaults)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def resolve_ib_api_mode(settings: IBSettings | None) -> str:
    if settings is None:
        return "ib"
    mode = str(getattr(settings, "api_mode", "") or "ib").strip().lower()
    if mode not in {"ib", "mock"}:
        return "ib"
    return mode


def _probe_ib_socket(host: str | None, port: int | None, timeout_seconds: float = 2.0) -> bool:
    if not host or not port:
        return False
    try:
        target = (str(host).strip(), int(port))
    except (TypeError, ValueError):
        return False
    try:
        with socket.create_connection(target, timeout=timeout_seconds):
            return True
    except OSError:
        return False


def get_or_create_ib_state(session) -> IBConnectionState:
    row = session.query(IBConnectionState).first()
    if row:
        return row
    row = IBConnectionState(status="unknown")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_ib_state(
    session,
    *,
    status: str | None = None,
    message: str | None = None,
    heartbeat: bool = True,
) -> IBConnectionState:
    row = get_or_create_ib_state(session)
    if status is not None:
        row.status = status
        if status == "degraded":
            if row.degraded_since is None:
                row.degraded_since = datetime.utcnow()
        elif status in {"connected", "mock"}:
            row.degraded_since = None
    if message is not None:
        row.message = message
    if heartbeat:
        row.last_heartbeat = datetime.utcnow()
    session.commit()
    session.refresh(row)
    return row


def ensure_ib_client_id(
    session,
    *,
    max_attempts: int = 5,
    timeout_seconds: float = 2.0,
) -> IBSettings:
    return get_or_create_ib_settings(session)

def read_bridge_status(session, *, mode: str, force: bool = False) -> dict:
    if session is None:
        return _read_bridge_status(resolve_bridge_root())
    return ensure_lean_bridge_live(session, mode=mode, force=force)


def probe_ib_connection(session, *, timeout_seconds: float = 2.0) -> IBConnectionState:
    settings = get_or_create_ib_settings(session)
    if resolve_ib_api_mode(settings) == "mock":
        return update_ib_state(
            session,
            status="mock",
            message="mock mode enabled",
            heartbeat=True,
        )
    if not _probe_ib_socket(settings.host, settings.port, timeout_seconds=timeout_seconds):
        return update_ib_state(
            session,
            status="disconnected",
            message="tws unreachable",
            heartbeat=True,
        )
    status_payload = read_bridge_status(session, mode=settings.mode or "paper", force=False)
    stale = bool(status_payload.get("stale", True))
    raw_status = str(status_payload.get("status") or "unknown").strip().lower()
    last_error = status_payload.get("last_error")

    if stale or raw_status == "missing":
        return update_ib_state(
            session,
            status="disconnected",
            message="lean bridge stale",
            heartbeat=True,
        )

    if raw_status in {"ok", "connected"}:
        return update_ib_state(
            session,
            status="connected",
            message="lean bridge ok",
            heartbeat=True,
        )

    message = str(last_error or f"lean bridge {raw_status}")
    return update_ib_state(
        session,
        status="degraded",
        message=message,
        heartbeat=True,
    )
