from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime

from app.models import IBConnectionState, IBSettings


def _resolve_default_settings() -> dict[str, object]:
    host = (os.getenv("IB_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int((os.getenv("IB_PORT") or "7497").strip() or 7497)
    client_id = int((os.getenv("IB_CLIENT_ID") or "1").strip() or 1)
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
    if message is not None:
        row.message = message
    if heartbeat:
        row.last_heartbeat = datetime.utcnow()
    session.commit()
    session.refresh(row)
    return row


def _probe_ib_api(
    host: str,
    port: int,
    client_id: int,
    timeout_seconds: float,
) -> tuple[str, str] | None:
    try:
        from ibapi.client import EClient
        from ibapi.wrapper import EWrapper
    except Exception:
        return None

    class ProbeClient(EWrapper, EClient):
        def __init__(self) -> None:
            EWrapper.__init__(self)
            EClient.__init__(self, self)
            self._ready = threading.Event()
            self._error: str | None = None

        def nextValidId(self, orderId: int) -> None:  # noqa: N802
            self._ready.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # type: ignore[override]  # noqa: N802
            fatal_codes = {502, 503, 504, 1100, 1101, 1102}
            if errorCode in fatal_codes:
                self._error = f"{errorCode} {errorString}"
                self._ready.set()

    client = ProbeClient()
    try:
        client.connect(host, int(port), int(client_id))
    except Exception as exc:
        return ("disconnected", f"ibapi connect failed ({exc.__class__.__name__})")

    thread = threading.Thread(target=client.run, daemon=True)
    thread.start()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if client._ready.wait(timeout=0.1):
            break

    status = "connected"
    message = "ibapi ok"
    if client._error:
        status = "disconnected"
        message = f"ibapi error {client._error}"
    elif not client._ready.is_set():
        status = "disconnected"
        message = "ibapi timeout"

    client.disconnect()
    return (status, message)


def probe_ib_connection(session, *, timeout_seconds: float = 2.0) -> IBConnectionState:
    settings = get_or_create_ib_settings(session)
    if resolve_ib_api_mode(settings) == "mock":
        return update_ib_state(
            session,
            status="mock",
            message="mock mode enabled",
            heartbeat=True,
        )
    host = settings.host
    port = settings.port
    client_id = settings.client_id
    api_result = _probe_ib_api(host, port, client_id, timeout_seconds)
    if api_result:
        status, message = api_result
        return update_ib_state(
            session,
            status=status,
            message=message,
            heartbeat=True,
        )
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return update_ib_state(
                session,
                status="connected",
                message=f"tcp ok {host}:{port}",
                heartbeat=True,
            )
    except OSError as exc:
        return update_ib_state(
            session,
            status="disconnected",
            message=f"tcp failed {host}:{port} ({exc.__class__.__name__})",
            heartbeat=True,
        )
