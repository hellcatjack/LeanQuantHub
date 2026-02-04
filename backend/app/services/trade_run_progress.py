from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings


@dataclass
class TradeRunProgress:
    last_progress_at: datetime
    progress_stage: str
    progress_reason: str | None


def _parse_session_time(value: str, fallback: time) -> time:
    text = str(value or "").strip()
    if not text:
        return fallback
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.time()
    return fallback


def is_market_open(now: datetime | None = None) -> bool:
    current = now or datetime.utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(settings.market_timezone)
    except Exception:
        zone = timezone.utc
    local = current.astimezone(zone)
    if local.weekday() >= 5:
        return False
    open_time = _parse_session_time(settings.market_session_open, time(9, 30))
    close_time = _parse_session_time(settings.market_session_close, time(16, 0))
    now_time = local.time()
    if open_time <= close_time:
        return open_time <= now_time <= close_time
    return now_time >= open_time or now_time <= close_time


def _resolve_progress_time(run) -> datetime | None:
    for value in (
        getattr(run, "last_progress_at", None),
        getattr(run, "started_at", None),
        getattr(run, "updated_at", None),
        getattr(run, "created_at", None),
    ):
        if isinstance(value, datetime):
            return value
    return None


def is_trade_run_stalled(
    run,
    now: datetime,
    *,
    window_minutes: int = 15,
    trading_open: bool = True,
) -> bool:
    if run is None:
        return False
    if str(getattr(run, "status", "") or "").lower() != "running":
        return False
    if not trading_open:
        return False
    progress_time = _resolve_progress_time(run)
    if progress_time is None:
        return False
    delta = now - progress_time
    return delta.total_seconds() >= max(0, int(window_minutes)) * 60


def update_trade_run_progress(session, run, stage: str, reason: str | None = None, *, commit: bool = True):
    if run is None:
        return None
    if str(getattr(run, "status", "") or "") not in {"running", "stalled"}:
        return run
    now = datetime.utcnow()
    run.last_progress_at = now
    run.progress_stage = stage
    run.progress_reason = reason
    run.updated_at = now
    if commit:
        session.commit()
        session.refresh(run)
    return run
