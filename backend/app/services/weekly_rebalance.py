from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db import SessionLocal
from app.models import AutoWeeklyJob, PreTradeRun, PreTradeTemplate, Project, TradeRun
from app.services.pretrade_runner import (
    _build_step_plan,
    _get_or_create_settings,
    create_pretrade_run_for_project,
    run_pretrade_run,
)
from app.services.trade_alerts import notify_trade_alert
from app.services.trade_executor import execute_trade_run
from app.services.trading_calendar import load_trading_days


PREPARE_DISABLED_STEPS = {"bridge_gate", "market_snapshot", "trade_execute"}
WEEKLY_REBALANCE_SCHEDULES = [
    {
        "phase": "prepare",
        "timer_unit": "stocklean-weekly-rebalance-prepare.timer",
        "service_unit": "stocklean-weekly-rebalance-prepare.service",
        "on_calendar": "Mon *-*-* 08:00:00",
        "description": "PreTrade weekly checklist before market open",
    },
    {
        "phase": "execute",
        "timer_unit": "stocklean-weekly-rebalance-execute.timer",
        "service_unit": "stocklean-weekly-rebalance-execute.service",
        "on_calendar": "Mon *-*-* 09:35:00",
        "description": "Execute weekly rebalance after market open",
    },
]


@dataclass
class WeeklyRebalanceResult:
    project_id: int
    phase: str
    status: str
    message: str | None
    week_key: str
    pretrade_run_id: int | None = None
    trade_run_id: int | None = None
    trade_status: str | None = None
    notification_sent: bool = False


def _market_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.market_timezone)
    except Exception:
        return ZoneInfo("America/New_York")


def _local_now(now: datetime | None = None) -> datetime:
    tz = _market_tz()
    if now is None:
        return datetime.now(timezone.utc).astimezone(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _week_key(local_dt: datetime) -> str:
    year, week, _ = local_dt.isocalendar()
    return f"{year}-W{week:02d}"


def _week_bounds_utc_naive(local_dt: datetime) -> tuple[datetime, datetime]:
    week_start = (local_dt - timedelta(days=local_dt.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    week_end = week_start + timedelta(days=7)
    return (
        week_start.astimezone(timezone.utc).replace(tzinfo=None),
        week_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _parse_session_time(value: str | None, fallback: time) -> time:
    text = str(value or "").strip()
    if not text:
        return fallback
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return fallback


def _market_open_at(local_dt: datetime) -> bool:
    if local_dt.weekday() >= 5:
        return False
    open_time = _parse_session_time(settings.market_session_open, time(9, 30))
    close_time = _parse_session_time(settings.market_session_close, time(16, 0))
    current = local_dt.time()
    if open_time <= close_time:
        return open_time <= current <= close_time
    return current >= open_time or current <= close_time


def _data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    return Path("/data/share/stock/data")


def _is_trading_day(day) -> bool:
    data_root = _data_root()
    try:
        days, _info = load_trading_days(
            data_root,
            data_root / "curated_adjusted",
            "SPY",
            ["Alpha"],
        )
    except Exception:
        return day.weekday() < 5
    return day in set(days)


def _prepare_step_plan(template) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for item in _build_step_plan(template):
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        key = str(next_item.get("key") or "").strip()
        if key in PREPARE_DISABLED_STEPS:
            next_item["enabled"] = False
        next_item.setdefault("params", {})
        plan.append(next_item)
    return plan


def _weekly_meta(phase: str, week_key: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phase": phase,
        "week_key": week_key,
    }
    payload.update(extra)
    return payload


def _matches_weekly_prepare(run: PreTradeRun, week_key: str) -> bool:
    params = run.params if isinstance(run.params, dict) else {}
    weekly = params.get("weekly_rebalance") if isinstance(params.get("weekly_rebalance"), dict) else {}
    return weekly.get("phase") == "prepare" and weekly.get("week_key") == week_key


def _find_prepare_run(session, *, project_id: int, week_key: str, local_dt: datetime) -> PreTradeRun | None:
    week_start, week_end = _week_bounds_utc_naive(local_dt)
    rows = (
        session.query(PreTradeRun)
        .filter(
            PreTradeRun.project_id == project_id,
            PreTradeRun.created_at >= week_start,
            PreTradeRun.created_at < week_end,
        )
        .order_by(PreTradeRun.created_at.desc(), PreTradeRun.id.desc())
        .all()
    )
    matches = [run for run in rows if _matches_weekly_prepare(run, week_key)]
    if not matches:
        return None
    for status in ("success", "running", "queued", "failed", "canceled"):
        for run in matches:
            if str(run.status or "").strip().lower() == status:
                return run
    return matches[0]


def _find_trade_run_for_pretrade(session, pretrade_run: PreTradeRun) -> TradeRun | None:
    rows = (
        session.query(TradeRun)
        .filter(TradeRun.project_id == pretrade_run.project_id)
        .order_by(TradeRun.created_at.desc(), TradeRun.id.desc())
        .limit(100)
        .all()
    )
    for run in rows:
        params = run.params if isinstance(run.params, dict) else {}
        try:
            pretrade_id = int(params.get("pretrade_run_id") or 0)
        except (TypeError, ValueError):
            pretrade_id = 0
        if pretrade_id == int(pretrade_run.id):
            return run
    return None


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return value.isoformat()
    return str(value)


def _weekly_meta_from_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    meta = params.get("weekly_rebalance")
    return dict(meta) if isinstance(meta, dict) else {}


def _normalize_limit(limit: int | None) -> int:
    try:
        value = int(limit or 20)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, 200))


def _result_payload(result: WeeklyRebalanceResult) -> dict[str, Any]:
    return {
        "phase": result.phase,
        "status": result.status,
        "message": result.message,
        "week_key": result.week_key,
        "project_id": result.project_id,
        "pretrade_run_id": result.pretrade_run_id,
        "trade_run_id": result.trade_run_id,
        "trade_status": result.trade_status,
        "notification_sent": result.notification_sent,
    }


def _record_weekly_rebalance_attempt(session, result: WeeklyRebalanceResult) -> None:
    if result.project_id is None or not session.get(Project, int(result.project_id)):
        return
    now = datetime.utcnow()
    session.add(
        AutoWeeklyJob(
            project_id=int(result.project_id),
            status=result.status,
            params={"weekly_rebalance": _result_payload(result)},
            message=result.message,
            started_at=now,
            ended_at=now,
        )
    )


def _finalize_result(
    result: WeeklyRebalanceResult,
    session: Any | None = None,
) -> WeeklyRebalanceResult:
    try:
        if session is not None:
            _record_weekly_rebalance_attempt(session, result)
            session.commit()
            return result
        with SessionLocal() as record_session:
            _record_weekly_rebalance_attempt(record_session, result)
            record_session.commit()
    except Exception:
        return result
    return result


def _read_systemd_timer_state(unit: str) -> dict[str, Any]:
    properties = [
        "ActiveState",
        "SubState",
        "LoadState",
        "UnitFileState",
        "NextElapseUSecRealtime",
        "LastTriggerUSec",
    ]
    try:
        completed = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                unit,
                *[f"--property={name}" for name in properties],
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception as exc:
        return {
            "active_state": None,
            "sub_state": None,
            "load_state": None,
            "unit_file_state": None,
            "next_elapse_at": None,
            "last_trigger_at": None,
            "error": str(exc),
        }
    parsed: dict[str, str] = {}
    for line in (completed.stdout or "").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            parsed[key.strip()] = value.strip()
    mapping = {
        "ActiveState": "active_state",
        "SubState": "sub_state",
        "LoadState": "load_state",
        "UnitFileState": "unit_file_state",
        "NextElapseUSecRealtime": "next_elapse_at",
        "LastTriggerUSec": "last_trigger_at",
    }
    result = {
        output_key: (parsed.get(input_key) or None)
        for input_key, output_key in mapping.items()
    }
    for key in ("next_elapse_at", "last_trigger_at"):
        if result.get(key) in {"n/a", "0"}:
            result[key] = None
    stderr = (completed.stderr or "").strip()
    result["error"] = None if completed.returncode == 0 else stderr or f"systemctl exited {completed.returncode}"
    return result


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _history_item(pretrade_run: PreTradeRun | None, trade_run: TradeRun | None) -> dict[str, Any]:
    pretrade_meta = _weekly_meta_from_params(pretrade_run.params if pretrade_run else None)
    trade_meta = _weekly_meta_from_params(trade_run.params if trade_run else None)
    week_key = (
        pretrade_meta.get("week_key")
        or trade_meta.get("week_key")
        or None
    )
    project_id = None
    if pretrade_run is not None:
        project_id = pretrade_run.project_id
    elif trade_run is not None:
        project_id = trade_run.project_id
    return {
        "project_id": project_id,
        "week_key": week_key,
        "phase": trade_meta.get("phase") or pretrade_meta.get("phase") or None,
        "pretrade_run_id": pretrade_run.id if pretrade_run else None,
        "pretrade_status": pretrade_run.status if pretrade_run else None,
        "pretrade_message": pretrade_run.message if pretrade_run else None,
        "pretrade_created_at": _to_iso(pretrade_run.created_at if pretrade_run else None),
        "pretrade_started_at": _to_iso(pretrade_run.started_at if pretrade_run else None),
        "pretrade_ended_at": _to_iso(pretrade_run.ended_at if pretrade_run else None),
        "pretrade_updated_at": _to_iso(pretrade_run.updated_at if pretrade_run else None),
        "trade_run_id": trade_run.id if trade_run else None,
        "trade_status": trade_run.status if trade_run else None,
        "trade_message": trade_run.message if trade_run else None,
        "trade_created_at": _to_iso(trade_run.created_at if trade_run else None),
        "trade_started_at": _to_iso(trade_run.started_at if trade_run else None),
        "trade_ended_at": _to_iso(trade_run.ended_at if trade_run else None),
        "trade_updated_at": _to_iso(getattr(trade_run, "updated_at", None) if trade_run else None),
        "attempt_id": None,
        "attempt_phase": None,
        "attempt_status": None,
        "attempt_message": None,
        "attempt_created_at": None,
        "attempt_started_at": None,
        "attempt_ended_at": None,
        "notification_sent": None,
        "weekly_rebalance": pretrade_meta or None,
        "trade_weekly_rebalance": trade_meta or None,
        "attempt_weekly_rebalance": None,
        "_sort_at": _to_iso(
            (trade_run.created_at if trade_run else None)
            or (pretrade_run.created_at if pretrade_run else None)
        ),
    }


def _merge_attempt(item: dict[str, Any], attempt: AutoWeeklyJob) -> dict[str, Any]:
    meta = _weekly_meta_from_params(attempt.params)
    attempt_created_at = _to_iso(getattr(attempt, "created_at", None))
    item["project_id"] = item.get("project_id") or getattr(attempt, "project_id", None)
    item["week_key"] = item.get("week_key") or meta.get("week_key")
    item["phase"] = item.get("phase") or meta.get("phase")
    item["attempt_id"] = attempt.id
    item["attempt_phase"] = meta.get("phase")
    item["attempt_status"] = meta.get("status") or attempt.status
    item["attempt_message"] = meta.get("message") or attempt.message
    item["attempt_created_at"] = attempt_created_at
    item["attempt_started_at"] = _to_iso(getattr(attempt, "started_at", None))
    item["attempt_ended_at"] = _to_iso(getattr(attempt, "ended_at", None))
    item["notification_sent"] = meta.get("notification_sent")
    item["attempt_weekly_rebalance"] = meta or None
    existing_sort = str(item.get("_sort_at") or "")
    if attempt_created_at and attempt_created_at > existing_sort:
        item["_sort_at"] = attempt_created_at
    return item


def _list_weekly_history(session, *, project_id: int | None, limit: int) -> list[dict[str, Any]]:
    scan_limit = max(limit * 5, 50)
    pretrade_query = session.query(PreTradeRun).order_by(
        PreTradeRun.created_at.desc(),
        PreTradeRun.id.desc(),
    )
    trade_query = session.query(TradeRun).order_by(
        TradeRun.created_at.desc(),
        TradeRun.id.desc(),
    )
    attempt_query = session.query(AutoWeeklyJob).order_by(
        AutoWeeklyJob.created_at.desc(),
        AutoWeeklyJob.id.desc(),
    )
    if project_id is not None:
        pretrade_query = pretrade_query.filter(PreTradeRun.project_id == int(project_id))
        trade_query = trade_query.filter(TradeRun.project_id == int(project_id))
        attempt_query = attempt_query.filter(AutoWeeklyJob.project_id == int(project_id))

    pretrade_runs = [
        run
        for run in pretrade_query.limit(scan_limit).all()
        if _weekly_meta_from_params(run.params)
    ]
    trade_runs = [
        run
        for run in trade_query.limit(scan_limit).all()
        if _weekly_meta_from_params(run.params)
        or (
            isinstance(run.params, dict)
            and run.params.get("pretrade_run_id") is not None
        )
    ]
    attempts = [
        row
        for row in attempt_query.limit(scan_limit).all()
        if _weekly_meta_from_params(row.params)
    ]

    trade_by_pretrade_id: dict[int, TradeRun] = {}
    trade_without_pretrade: list[TradeRun] = []
    for trade_run in trade_runs:
        pretrade_id = None
        if isinstance(trade_run.params, dict):
            try:
                pretrade_id = int(trade_run.params.get("pretrade_run_id") or 0) or None
            except (TypeError, ValueError):
                pretrade_id = None
        if pretrade_id:
            trade_by_pretrade_id.setdefault(pretrade_id, trade_run)
        elif _weekly_meta_from_params(trade_run.params):
            trade_without_pretrade.append(trade_run)

    items: list[dict[str, Any]] = []
    item_by_pretrade_id: dict[int, dict[str, Any]] = {}
    item_by_trade_id: dict[int, dict[str, Any]] = {}
    seen_trade_ids: set[int] = set()
    for pretrade_run in pretrade_runs:
        trade_run = trade_by_pretrade_id.get(int(pretrade_run.id))
        if trade_run:
            seen_trade_ids.add(int(trade_run.id))
        item = _history_item(pretrade_run, trade_run)
        items.append(item)
        item_by_pretrade_id[int(pretrade_run.id)] = item
        if trade_run:
            item_by_trade_id[int(trade_run.id)] = item
    for trade_run in trade_without_pretrade:
        if int(trade_run.id) in seen_trade_ids:
            continue
        item = _history_item(None, trade_run)
        items.append(item)
        item_by_trade_id[int(trade_run.id)] = item

    seen_attempt_ids: set[int] = set()
    for attempt in attempts:
        meta = _weekly_meta_from_params(attempt.params)
        pretrade_id = _coerce_positive_int(meta.get("pretrade_run_id"))
        trade_id = _coerce_positive_int(meta.get("trade_run_id"))
        target = None
        if pretrade_id:
            target = item_by_pretrade_id.get(pretrade_id)
        if target is None and trade_id:
            target = item_by_trade_id.get(trade_id)
        if target is None:
            continue
        _merge_attempt(target, attempt)
        seen_attempt_ids.add(int(attempt.id))
    for attempt in attempts:
        if int(attempt.id) in seen_attempt_ids:
            continue
        items.append(_merge_attempt(_history_item(None, None), attempt))

    items.sort(key=lambda item: str(item.get("_sort_at") or ""), reverse=True)
    for item in items:
        item.pop("_sort_at", None)
    return items[:limit]


def get_weekly_rebalance_status(
    *,
    project_id: int | None = None,
    limit: int | None = 20,
) -> dict[str, Any]:
    normalized_limit = _normalize_limit(limit)
    schedules: list[dict[str, Any]] = []
    for schedule in WEEKLY_REBALANCE_SCHEDULES:
        timer_state = _read_systemd_timer_state(str(schedule["timer_unit"]))
        schedules.append(
            {
                **schedule,
                **timer_state,
            }
        )
    with SessionLocal() as session:
        history = _list_weekly_history(
            session,
            project_id=int(project_id) if project_id is not None else None,
            limit=normalized_limit,
        )
    return {
        "project_id": int(project_id) if project_id is not None else None,
        "generated_at": _to_iso(datetime.utcnow()),
        "schedules": schedules,
        "history": history,
    }


def _notify(session, message: str) -> bool:
    try:
        return bool(notify_trade_alert(session, message))
    except Exception:
        return False


def _prepare_message(result: WeeklyRebalanceResult) -> str:
    return (
        f"Weekly rebalance {result.phase} {result.status}: "
        f"project={result.project_id} week={result.week_key} "
        f"pretrade_run={result.pretrade_run_id or '-'} "
        f"trade_run={result.trade_run_id or '-'} "
        f"trade_status={result.trade_status or '-'} "
        f"message={result.message or '-'}"
    )


def prepare_weekly_rebalance(
    project_id: int,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> WeeklyRebalanceResult:
    local_dt = _local_now(now)
    week_key = _week_key(local_dt)
    if local_dt.weekday() != 0 and not force:
        return _finalize_result(
            WeeklyRebalanceResult(
                project_id=project_id,
                phase="prepare",
                status="skipped",
                message="not_rebalance_day",
                week_key=week_key,
            )
        )
    if not _is_trading_day(local_dt.date()) and not force:
        return _finalize_result(
            WeeklyRebalanceResult(
                project_id=project_id,
                phase="prepare",
                status="skipped",
                message="not_trading_day",
                week_key=week_key,
            )
        )
    if _market_open_at(local_dt) and not force:
        return _finalize_result(
            WeeklyRebalanceResult(
                project_id=project_id,
                phase="prepare",
                status="skipped",
                message="market_already_open",
                week_key=week_key,
            )
        )

    with SessionLocal() as session:
        project = session.get(Project, int(project_id))
        if not project:
            return _finalize_result(
                WeeklyRebalanceResult(
                    project_id=project_id,
                    phase="prepare",
                    status="failed",
                    message="project_not_found",
                    week_key=week_key,
                ),
                session,
            )
        existing = _find_prepare_run(
            session,
            project_id=int(project_id),
            week_key=week_key,
            local_dt=local_dt,
        )
        if existing and str(existing.status or "").lower() in {"success", "queued", "running"}:
            trade_run = _find_trade_run_for_pretrade(session, existing)
            result = WeeklyRebalanceResult(
                project_id=int(project_id),
                phase="prepare",
                status="reused",
                message=str(existing.message or "existing_prepare_run"),
                week_key=week_key,
                pretrade_run_id=existing.id,
                trade_run_id=trade_run.id if trade_run else None,
                trade_status=trade_run.status if trade_run else None,
            )
            result.notification_sent = _notify(session, _prepare_message(result))
            return _finalize_result(result, session)
        if existing and str(existing.status or "").lower() == "failed" and not force:
            trade_run = _find_trade_run_for_pretrade(session, existing)
            result = WeeklyRebalanceResult(
                project_id=int(project_id),
                phase="prepare",
                status="failed",
                message=str(existing.message or "existing_prepare_failed"),
                week_key=week_key,
                pretrade_run_id=existing.id,
                trade_run_id=trade_run.id if trade_run else None,
                trade_status=trade_run.status if trade_run else None,
            )
            result.notification_sent = _notify(session, _prepare_message(result))
            return _finalize_result(result, session)

        settings_row = _get_or_create_settings(session)
        template = None
        if settings_row.current_template_id:
            template = session.get(PreTradeTemplate, int(settings_row.current_template_id))
        run = create_pretrade_run_for_project(
            session,
            project_id=int(project_id),
            template_id=template.id if template else None,
            params={
                "weekly_rebalance": _weekly_meta(
                    "prepare",
                    week_key,
                    scheduled_at=local_dt.isoformat(),
                    prepared_at=datetime.utcnow().isoformat() + "Z",
                )
            },
            step_plan=_prepare_step_plan(template),
        )
        run_id = int(run.id)

    run_pretrade_run(run_id)

    with SessionLocal() as session:
        refreshed = session.get(PreTradeRun, run_id)
        trade_run = _find_trade_run_for_pretrade(session, refreshed) if refreshed else None
        status = str(refreshed.status if refreshed else "failed")
        result = WeeklyRebalanceResult(
            project_id=int(project_id),
            phase="prepare",
            status=status,
            message=refreshed.message if refreshed else "pretrade_run_missing",
            week_key=week_key,
            pretrade_run_id=refreshed.id if refreshed else run_id,
            trade_run_id=trade_run.id if trade_run else None,
            trade_status=trade_run.status if trade_run else None,
        )
        result.notification_sent = _notify(session, _prepare_message(result))
        return _finalize_result(result, session)


def execute_weekly_rebalance(
    project_id: int,
    *,
    now: datetime | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> WeeklyRebalanceResult:
    local_dt = _local_now(now)
    week_key = _week_key(local_dt)
    if local_dt.weekday() != 0 and not force:
        return _finalize_result(
            WeeklyRebalanceResult(
                project_id=project_id,
                phase="execute",
                status="skipped",
                message="not_rebalance_day",
                week_key=week_key,
            )
        )
    if not _is_trading_day(local_dt.date()) and not force:
        return _finalize_result(
            WeeklyRebalanceResult(
                project_id=project_id,
                phase="execute",
                status="skipped",
                message="not_trading_day",
                week_key=week_key,
            )
        )
    if not _market_open_at(local_dt) and not force:
        return _finalize_result(
            WeeklyRebalanceResult(
                project_id=project_id,
                phase="execute",
                status="skipped",
                message="market_not_open",
                week_key=week_key,
            )
        )

    with SessionLocal() as session:
        prepare_run = _find_prepare_run(
            session,
            project_id=int(project_id),
            week_key=week_key,
            local_dt=local_dt,
        )
        if not prepare_run:
            result = WeeklyRebalanceResult(
                project_id=int(project_id),
                phase="execute",
                status="blocked",
                message="prepare_run_missing",
                week_key=week_key,
            )
            result.notification_sent = _notify(session, _prepare_message(result))
            return _finalize_result(result, session)
        if str(prepare_run.status or "").lower() != "success" and not force:
            result = WeeklyRebalanceResult(
                project_id=int(project_id),
                phase="execute",
                status="blocked",
                message=f"prepare_run_not_success:{prepare_run.status}",
                week_key=week_key,
                pretrade_run_id=prepare_run.id,
            )
            result.notification_sent = _notify(session, _prepare_message(result))
            return _finalize_result(result, session)

        trade_run = _find_trade_run_for_pretrade(session, prepare_run)
        if not trade_run:
            result = WeeklyRebalanceResult(
                project_id=int(project_id),
                phase="execute",
                status="blocked",
                message="trade_run_missing",
                week_key=week_key,
                pretrade_run_id=prepare_run.id,
            )
            result.notification_sent = _notify(session, _prepare_message(result))
            return _finalize_result(result, session)
        trade_status = str(trade_run.status or "").strip().lower()
        if trade_status != "queued" and not force:
            result = WeeklyRebalanceResult(
                project_id=int(project_id),
                phase="execute",
                status=trade_status or "reused",
                message=f"trade_run_already_{trade_status or 'processed'}",
                week_key=week_key,
                pretrade_run_id=prepare_run.id,
                trade_run_id=trade_run.id,
                trade_status=trade_run.status,
            )
            result.notification_sent = _notify(session, _prepare_message(result))
            return _finalize_result(result, session)

        params = dict(trade_run.params or {})
        params["weekly_rebalance"] = _weekly_meta(
            "execute",
            week_key,
            pretrade_run_id=prepare_run.id,
            scheduled_at=local_dt.isoformat(),
            executed_at=datetime.utcnow().isoformat() + "Z",
        )
        params["execution_session"] = "rth"
        params["allow_outside_rth"] = False
        trade_run.params = params
        trade_run.updated_at = datetime.utcnow()
        session.commit()
        trade_run_id = int(trade_run.id)
        pretrade_run_id = int(prepare_run.id)

    try:
        execution = execute_trade_run(trade_run_id, dry_run=dry_run, force=force)
    except Exception as exc:
        with SessionLocal() as session:
            result = WeeklyRebalanceResult(
                project_id=int(project_id),
                phase="execute",
                status="failed",
                message=f"execution_error:{exc}",
                week_key=week_key,
                pretrade_run_id=pretrade_run_id,
                trade_run_id=trade_run_id,
                trade_status="failed",
            )
            result.notification_sent = _notify(session, _prepare_message(result))
            return _finalize_result(result, session)

    with SessionLocal() as session:
        refreshed = session.get(TradeRun, trade_run_id)
        result = WeeklyRebalanceResult(
            project_id=int(project_id),
            phase="execute",
            status=str(execution.status or (refreshed.status if refreshed else "unknown")),
            message=str(execution.message or (refreshed.message if refreshed else "") or ""),
            week_key=week_key,
            pretrade_run_id=pretrade_run_id,
            trade_run_id=trade_run_id,
            trade_status=refreshed.status if refreshed else execution.status,
        )
        result.notification_sent = _notify(session, _prepare_message(result))
        return _finalize_result(result, session)
