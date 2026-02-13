from __future__ import annotations

import json
import os
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_

from app.core.config import settings
from app.models import IBClientIdPool, LeanExecutorPool, TradeOrder


class ClientIdPoolExhausted(RuntimeError):
    pass


_TERMINAL_TRADE_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "INVALID", "SKIPPED"}


def _pool_base(mode: str) -> int:
    base = settings.ib_client_id_pool_base
    if str(mode).lower() == "live":
        base += settings.ib_client_id_live_offset
    return base


def _ensure_pool(session, *, mode: str) -> None:
    base = _pool_base(mode)
    size = settings.ib_client_id_pool_size
    upper = base + size
    existing = {
        row.client_id
        for row in session.query(IBClientIdPool.client_id)
        .filter(and_(IBClientIdPool.client_id >= base, IBClientIdPool.client_id < upper))
        .all()
    }
    missing = [cid for cid in range(base, upper) if cid not in existing]
    if not missing:
        return
    for cid in missing:
        session.add(IBClientIdPool(client_id=cid, status="free"))
    session.commit()


def _build_worker_order_by(dialect_name: str | None):
    name = str(dialect_name or "").lower()
    if name in {"mysql", "mariadb"}:
        return (
            LeanExecutorPool.last_order_at.asc(),
            LeanExecutorPool.client_id.asc(),
        )
    return (
        LeanExecutorPool.last_order_at.asc().nullsfirst(),
        LeanExecutorPool.client_id.asc(),
    )


def select_worker_client_id(session, *, mode: str) -> int | None:
    dialect_name = session.bind.dialect.name if session.bind else None
    query = (
        session.query(LeanExecutorPool)
        .filter(
            and_(
                LeanExecutorPool.mode == mode,
                LeanExecutorPool.role == "worker",
            )
        )
        .order_by(*_build_worker_order_by(dialect_name))
    )
    worker = query.first()
    if worker is None:
        return None
    worker.last_order_at = datetime.utcnow()
    session.commit()
    return int(worker.client_id)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    text = ts.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _to_naive_utc(parsed)


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _read_bridge_heartbeat(output_dir: str | None) -> datetime | None:
    if not output_dir:
        return None
    path = Path(output_dir) / "lean_bridge_status.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_iso(str(payload.get("last_heartbeat") or ""))


def reap_stale_leases(session, *, mode: str, now: datetime | None = None) -> int:
    now = _to_naive_utc(now or datetime.utcnow())
    base = _pool_base(mode)
    upper = base + settings.ib_client_id_pool_size
    ttl = timedelta(seconds=settings.ib_client_id_lease_ttl_seconds)
    heartbeat_timeout = timedelta(seconds=settings.lean_bridge_heartbeat_timeout_seconds)

    leases = (
        session.query(IBClientIdPool)
        .filter(
            and_(
                IBClientIdPool.client_id >= base,
                IBClientIdPool.client_id < upper,
                IBClientIdPool.status == "leased",
            )
        )
        .all()
    )
    released = 0
    for lease in leases:
        heartbeat = _to_naive_utc(_read_bridge_heartbeat(lease.output_dir))
        lease.last_heartbeat = heartbeat

        acquired = _to_naive_utc(lease.acquired_at) or now
        pid_dead = lease.pid is not None and not _pid_alive(lease.pid)
        heartbeat_stale = False
        if heartbeat is None:
            heartbeat_stale = now - acquired > heartbeat_timeout
        else:
            heartbeat_stale = now - heartbeat > heartbeat_timeout
        too_old = lease.pid is None and now - acquired > ttl

        should_release = pid_dead or heartbeat_stale or too_old

        # If the lease is tied to an order that is still active, keep the client id reserved even
        # if the original Lean process died. This avoids reusing the same ib-client-id while the
        # order remains open in TWS, which would break manual cancels and status reconciliation.
        if should_release and lease.order_id is not None:
            order_status = (
                session.query(TradeOrder.status)
                .filter(TradeOrder.id == int(lease.order_id))
                .scalar()
            )
            if order_status and str(order_status).strip().upper() not in _TERMINAL_TRADE_ORDER_STATUSES:
                # Keep lease as-is (best-effort). We still record heartbeats above.
                continue

        if should_release:
            if lease.pid is not None:
                _kill_pid(lease.pid)
            lease.status = "free"
            lease.released_at = now
            lease.release_reason = "stale_or_dead"
            lease.order_id = None
            lease.pid = None
            lease.output_dir = None
            lease.lease_token = None
            released += 1

    if released:
        session.commit()
    return released


def lease_client_id(session, *, order_id: int, mode: str, output_dir: str) -> IBClientIdPool:
    _ensure_pool(session, mode=mode)
    reap_stale_leases(session, mode=mode)
    base = _pool_base(mode)
    upper = base + settings.ib_client_id_pool_size

    query = session.query(IBClientIdPool).filter(
        and_(
            IBClientIdPool.client_id >= base,
            IBClientIdPool.client_id < upper,
            IBClientIdPool.status != "leased",
        )
    ).order_by(IBClientIdPool.client_id.asc())

    if session.bind and session.bind.dialect.name != "sqlite":
        query = query.with_for_update()

    lease = query.first()
    if lease is None:
        raise ClientIdPoolExhausted("client_id_busy")

    now = datetime.utcnow()
    lease.status = "leased"
    lease.order_id = order_id
    lease.output_dir = output_dir
    lease.lease_token = uuid4().hex
    lease.acquired_at = now
    lease.last_heartbeat = now
    lease.released_at = None
    lease.release_reason = None
    session.commit()
    session.refresh(lease)
    return lease


def attach_lease_pid(session, *, lease_token: str, pid: int) -> None:
    lease = session.query(IBClientIdPool).filter(IBClientIdPool.lease_token == lease_token).first()
    if lease is None:
        return
    lease.pid = pid
    session.commit()
