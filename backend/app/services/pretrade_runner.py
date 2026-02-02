from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as time_cls, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import urllib.request
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db import SessionLocal
from app.models import (
    BulkSyncJob,
    Dataset,
    FactorScoreJob,
    MLTrainJob,
    PitFundamentalJob,
    PitWeeklyJob,
    PreTradeRun,
    PreTradeSettings,
    PreTradeStep,
    PreTradeTemplate,
    Project,
    DecisionSnapshot,
    TradeRun,
)
from app.routes.datasets import (
    _alpha_listing_age,
    _audit_alpha_coverage,
    _audit_trade_coverage,
    _bulk_job_counts,
    _refresh_alpha_listing,
    _start_bulk_sync_worker,
)
from app.routes.projects import _get_latest_version, _resolve_project_config, PROJECT_CONFIG_TAG
from app.services.alpha_fetch import load_alpha_fetch_config
from app.services.alpha_rate import load_alpha_rate_config
from app.services.bulk_auto import load_bulk_auto_config
from app.services.decision_snapshot import generate_decision_snapshot
from app.services.factor_score_runner import run_factor_score_job
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import (
    parse_bridge_timestamp,
    read_bridge_payload,
    read_positions,
    read_quotes,
)
from app.services.lean_bridge_watchlist import (
    merge_symbols,
    resolve_watchlist_path,
    write_watchlist,
)
from app.services.ib_settings import update_ib_state
from app.services.job_lock import JobLock
from app.services.ml_runner import build_ml_config, run_ml_train
from app.services.pit_runner import (
    _build_fundamental_fetch_command,
    run_pit_fundamental_job,
    run_pit_weekly_job,
)
from app.services.trading_calendar import (
    load_trading_calendar_config,
    load_trading_calendar_meta,
    load_trading_days,
    trading_calendar_csv_path,
)
from app.services.project_symbols import (
    collect_active_project_symbols,
    collect_project_symbols,
    write_symbol_list,
)
from app.services.trade_executor import execute_trade_run

PRETRADE_ACTIVE_STATUSES = {"queued", "running"}


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _read_snapshot_symbols(path: str | None) -> list[str]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    symbols: set[str] = set()
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = _normalize_symbol(row.get("symbol"))
            if symbol:
                symbols.add(symbol)
    return sorted(symbols)


def _clip_symbols(symbols: list[str], max_symbols: int | None) -> list[str]:
    items = sorted({_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)})
    if max_symbols is not None:
        try:
            limit = max(0, int(max_symbols))
        except (TypeError, ValueError):
            limit = None
        if limit:
            return items[:limit]
    return items


def _build_snapshot_symbols(
    session,
    *,
    project_id: int,
    decision_snapshot_id: int | None = None,
    max_symbols: int | None = None,
) -> list[str]:
    if decision_snapshot_id:
        snapshot = session.get(DecisionSnapshot, decision_snapshot_id)
        if snapshot:
            symbols = _read_snapshot_symbols(snapshot.items_path)
            if symbols:
                return _clip_symbols(symbols, max_symbols)
    config = _resolve_project_config(session, project_id)
    return _clip_symbols(collect_project_symbols(config), max_symbols)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _quote_timestamp(item: dict[str, Any], fallback: str | None) -> datetime | None:
    ts = item.get("timestamp")
    if isinstance(ts, str):
        parsed = _parse_timestamp(ts)
        if parsed:
            return parsed
    payload = item.get("data") if isinstance(item.get("data"), dict) else None
    if isinstance(payload, dict):
        ts = payload.get("timestamp")
        if isinstance(ts, str):
            parsed = _parse_timestamp(ts)
            if parsed:
                return parsed
    return _parse_timestamp(fallback)


def _quotes_ready(symbols: list[str], ttl_seconds: int | None) -> tuple[bool, list[str], list[str]]:
    if ttl_seconds is None:
        return False, symbols, []
    quotes = read_quotes(_resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    stale = bool(quotes.get("stale", False))
    updated_at = quotes.get("updated_at") or quotes.get("refreshed_at")
    now = datetime.utcnow()
    ttl = max(0, int(ttl_seconds))
    quotes_map = {
        _normalize_symbol(item.get("symbol")): item
        for item in items
        if isinstance(item, dict) and _normalize_symbol(item.get("symbol"))
    }
    missing: list[str] = []
    stale_symbols: list[str] = []
    for symbol in symbols:
        item = quotes_map.get(symbol)
        if not item:
            missing.append(symbol)
            continue
        ts = _quote_timestamp(item, updated_at)
        if stale and ts is None:
            stale_symbols.append(symbol)
            continue
        if ts and ttl > 0 and now - ts > timedelta(seconds=ttl):
            stale_symbols.append(symbol)
    ok = not missing and not stale_symbols
    return ok, missing, stale_symbols


def _coerce_ttl(value: int | None, default: int) -> int:
    try:
        ttl = int(value) if value is not None else default
    except (TypeError, ValueError):
        ttl = default
    if ttl <= 0:
        ttl = default
    return ttl


def _bridge_payload_check(
    root: Path,
    *,
    filename: str,
    ttl_seconds: int,
    timestamp_keys: list[str],
) -> dict[str, Any]:
    payload = read_bridge_payload(root, filename)
    if payload is None:
        return {
            "ok": False,
            "missing": True,
            "updated_at": None,
            "ttl_seconds": ttl_seconds,
            "age_seconds": None,
            "items": None,
        }
    ts = parse_bridge_timestamp(payload, timestamp_keys)
    now = datetime.now(timezone.utc)
    age_seconds = int((now - ts).total_seconds()) if ts else None
    ok = bool(ts and age_seconds is not None and age_seconds <= ttl_seconds)
    items = payload.get("items")
    count = len(items) if isinstance(items, list) else None
    return {
        "ok": ok,
        "missing": False,
        "updated_at": ts.isoformat() if ts else None,
        "ttl_seconds": ttl_seconds,
        "age_seconds": age_seconds,
        "items": count,
    }


@dataclass
class StepResult:
    artifacts: dict[str, Any] | None = None
    log_path: str | None = None


class StepSkip(RuntimeError):
    def __init__(self, reason: str, artifacts: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.artifacts = artifacts or {}


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _fundamentals_cache_meta_path(data_root: Path) -> Path:
    return data_root / "fundamentals" / "alpha" / "fundamentals_cache.json"


FUNDAMENTALS_REQUIRED_FILES = (
    "overview.json",
    "income_statement.json",
    "balance_sheet.json",
    "cash_flow.json",
)


def _parse_date_text(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _last_friday(today: date) -> date:
    delta = (today.weekday() - 4) % 7
    return today - timedelta(days=delta)


def _fundamentals_cache_fresh(data_root: Path, today: date) -> tuple[bool, date]:
    last_friday = _last_friday(today)
    meta_path = _fundamentals_cache_meta_path(data_root)
    if not meta_path.exists():
        return False, last_friday
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, last_friday
    if not isinstance(payload, dict):
        return False, last_friday
    cached = _parse_date_text(str(payload.get("as_of") or ""))
    if cached and cached >= last_friday:
        return True, last_friday
    return False, last_friday


def _parse_datetime_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = text[:-1] if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return _parse_date_text(cleaned)


def _fundamentals_status_map(data_root: Path) -> dict[str, dict[str, str]]:
    status_path = data_root / "fundamentals" / "alpha" / "fundamentals_status.csv"
    if not status_path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with status_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = _normalize_symbol(row.get("symbol"))
            if not symbol:
                continue
            rows[symbol] = {str(k): str(v or "") for k, v in row.items()}
    return rows


def _fundamentals_symbol_fresh(
    data_root: Path,
    symbol: str,
    last_friday: date,
    *,
    status_map: dict[str, dict[str, str]] | None = None,
) -> bool:
    symbol_norm = _normalize_symbol(symbol)
    if not symbol_norm:
        return False
    if status_map is None:
        status_map = _fundamentals_status_map(data_root)
    row = status_map.get(symbol_norm)
    if not row:
        return False
    status_value = str(row.get("status") or "").strip().lower()
    if status_value != "ok":
        return False
    updated_at = _parse_datetime_date(row.get("updated_at"))
    if not updated_at or updated_at < last_friday:
        return False
    symbol_dir = data_root / "fundamentals" / "alpha" / symbol_norm
    for filename in FUNDAMENTALS_REQUIRED_FILES:
        path = symbol_dir / filename
        if not path.exists():
            return False
        mtime_date = datetime.utcfromtimestamp(path.stat().st_mtime).date()
        if mtime_date < last_friday:
            return False
    return True


def _fundamentals_missing_symbols(
    data_root: Path,
    symbols: list[str],
    last_friday: date,
) -> list[str]:
    status_map = _fundamentals_status_map(data_root)
    missing: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        symbol_norm = _normalize_symbol(symbol)
        if not symbol_norm or symbol_norm in seen:
            continue
        seen.add(symbol_norm)
        if not _fundamentals_symbol_fresh(
            data_root, symbol_norm, last_friday, status_map=status_map
        ):
            missing.append(symbol_norm)
    return sorted(missing)


def _write_fundamentals_cache_meta(data_root: Path, as_of: date) -> None:
    meta_path = _fundamentals_cache_meta_path(data_root)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": as_of.isoformat(),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_watchlist(symbols: list[str]) -> Path:
    path = resolve_bridge_root() / "watchlist.json"
    payload = {
        "symbols": sorted({_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)}),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _ensure_log_dir(run_id: int) -> Path:
    log_dir = Path(settings.artifact_root) / f"pretrade_run_{run_id}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


@dataclass
class StepContext:
    session: SessionLocal
    run: PreTradeRun
    step: PreTradeStep

    def update(
        self,
        *,
        status: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        artifacts: dict[str, Any] | None = None,
        log_path: str | None = None,
    ) -> None:
        if status is not None:
            self.step.status = status
        if progress is not None:
            self.step.progress = progress
        if message is not None:
            self.step.message = message
        if artifacts is not None:
            merged = dict(self.step.artifacts or {})
            merged.update(artifacts)
            self.step.artifacts = merged
        if log_path is not None:
            self.step.log_path = log_path
        self.step.updated_at = datetime.utcnow()
        self.session.commit()


def _get_or_create_settings(session) -> PreTradeSettings:
    settings_row = session.query(PreTradeSettings).first()
    if settings_row:
        return settings_row
    settings_row = PreTradeSettings(
        max_retries=0,
        retry_base_delay_seconds=60,
        retry_max_delay_seconds=1800,
        deadline_timezone="America/New_York",
        update_project_only=True,
        bridge_heartbeat_ttl_seconds=60,
        bridge_account_ttl_seconds=300,
        bridge_positions_ttl_seconds=300,
        bridge_quotes_ttl_seconds=60,
    )
    session.add(settings_row)
    session.commit()
    session.refresh(settings_row)
    return settings_row


def _compute_deadline_at(run: PreTradeRun, settings_row: PreTradeSettings) -> datetime | None:
    if run.deadline_at:
        return run.deadline_at
    deadline_time = (settings_row.deadline_time or "").strip()
    if not deadline_time:
        return None
    tz_name = (settings_row.deadline_timezone or "America/New_York").strip()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")
    if run.window_end:
        base_date = run.window_end.date()
    else:
        base_date = datetime.now(tz).date()
    parts = deadline_time.split(":")
    hour = int(parts[0]) if parts and parts[0].isdigit() else 9
    minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
    dt = datetime.combine(base_date, time_cls(hour=hour, minute=minute))
    return dt.replace(tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _should_retry(
    now: datetime,
    deadline_at: datetime | None,
    settings_row: PreTradeSettings,
    retry_count: int,
) -> bool:
    if deadline_at and now >= deadline_at:
        return False
    max_retries = int(settings_row.max_retries or 0)
    if max_retries <= 0:
        return True
    if deadline_at and now < deadline_at:
        return True
    return retry_count <= max_retries


def _compute_retry_delay(settings_row: PreTradeSettings, retry_count: int) -> int:
    base = int(settings_row.retry_base_delay_seconds or 60)
    max_delay = int(settings_row.retry_max_delay_seconds or 1800)
    if retry_count <= 1:
        delay = base
    else:
        delay = base * (2 ** (retry_count - 1))
    return max(1, min(delay, max_delay))


def _notify_telegram(settings_row: PreTradeSettings, message: str) -> None:
    token = (settings_row.telegram_bot_token or "").strip()
    chat_id = (settings_row.telegram_chat_id or "").strip()
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as _:
            return
    except Exception:
        return


def _resolve_spy_dataset(session) -> Dataset | None:
    dataset = (
        session.query(Dataset)
        .filter(Dataset.source_path == "alpha:spy")
        .first()
    )
    if dataset:
        return dataset
    return session.query(Dataset).filter(Dataset.name == "Alpha_SPY_Daily").first()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _latest_trading_day(data_root: Path, benchmark: str) -> tuple[date | None, dict[str, Any]]:
    adjusted_dir = data_root / "curated_adjusted"
    vendor_preference = ["Alpha"]
    days, info = load_trading_days(data_root, adjusted_dir, benchmark, vendor_preference)
    today = datetime.utcnow().date()
    candidates = [day for day in days if day < today]
    if not candidates:
        return None, info
    return max(candidates), info


StepHandler = Callable[[StepContext, dict[str, Any]], StepResult]


STEP_DEFS: list[tuple[str, StepHandler]] = []


def step_calendar_refresh(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    data_root = _resolve_data_root()
    config = load_trading_calendar_config(data_root)
    meta = load_trading_calendar_meta(data_root)
    refresh_days = int(config.get("refresh_days") or 0)
    generated_at = meta.get("generated_at")
    artifacts = {
        "calendar_source": meta.get("source"),
        "calendar_generated_at": generated_at,
        "calendar_path": str(trading_calendar_csv_path(data_root, config.get("exchange") or "")),
        "refresh_days": refresh_days,
    }
    if generated_at and refresh_days > 0:
        try:
            generated = datetime.fromisoformat(generated_at)
        except ValueError:
            generated = None
        if generated:
            age_days = (datetime.utcnow() - generated).days
            artifacts["calendar_age_days"] = age_days
            if age_days < refresh_days:
                raise StepSkip("calendar_fresh", artifacts=artifacts)

    log_dir = _ensure_log_dir(ctx.run.id)
    log_path = log_dir / "trading_calendar_refresh.log"
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "build_trading_calendar.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--data-root",
        str(data_root),
        "--exchange",
        str(config.get("exchange") or "XNYS"),
        "--start",
        str(config.get("start_date") or ""),
        "--end",
        str(config.get("end_date") or ""),
        "--refresh-days",
        str(config.get("refresh_days") or 0),
    ]
    with log_path.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"trading_calendar_refresh_failed log={log_path}")
    return StepResult(artifacts=artifacts, log_path=str(log_path))


def step_trading_day_check(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    data_root = _resolve_data_root()
    benchmark = (params.get("benchmark") or "SPY").strip().upper()
    last_day, info = _latest_trading_day(data_root, benchmark)
    if not last_day:
        raise RuntimeError("missing_trading_day")
    dataset = _resolve_spy_dataset(ctx.session)
    coverage_end = _parse_date(dataset.coverage_end if dataset else None)
    if not coverage_end:
        raise RuntimeError("spy_coverage_missing")
    if coverage_end < last_day:
        raise RuntimeError(
            f"coverage_end_lt_last_trading_day: {coverage_end} < {last_day}"
        )
    artifacts = {
        "benchmark": benchmark,
        "last_trading_day": last_day.isoformat(),
        "coverage_end": coverage_end.isoformat(),
        "calendar_source": info.get("calendar_source"),
        "calendar_start": info.get("calendar_start"),
        "calendar_end": info.get("calendar_end"),
        "calendar_path": info.get("calendar_path"),
    }
    return StepResult(artifacts=artifacts)


def step_price_incremental(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    data_root = _resolve_data_root()
    bulk_config = load_bulk_auto_config(data_root)
    fetch_config = load_alpha_fetch_config(data_root)
    rate_config = load_alpha_rate_config(data_root)
    settings_row = _get_or_create_settings(ctx.session)
    symbol_whitelist_path: str | None = None
    symbol_whitelist_count: int | None = None
    if settings_row.update_project_only:
        symbols, benchmarks = collect_active_project_symbols(ctx.session)
        if not symbols:
            raise StepSkip(
                "project_symbols_empty",
                artifacts={
                    "symbol_whitelist_count": 0,
                    "symbol_whitelist_benchmarks": benchmarks,
                },
            )
        log_dir = _ensure_log_dir(ctx.run.id)
        symbol_path = log_dir / "project_symbols.csv"
        write_symbol_list(symbol_path, symbols)
        symbol_whitelist_path = str(symbol_path)
        symbol_whitelist_count = len(symbols)
    min_delay = float(params.get("min_delay_seconds") or bulk_config.get("min_delay_seconds") or 0)
    effective_min_delay = float(rate_config.get("effective_min_delay_seconds") or 0)
    if effective_min_delay > min_delay:
        min_delay = effective_min_delay
    payload = {
        "status": bulk_config.get("status") or "all",
        "batch_size": int(bulk_config.get("batch_size") or 200),
        "only_missing": bool(bulk_config.get("only_missing", True)),
        "auto_sync": True,
        "refresh_listing": False,
        "refresh_listing_mode": bulk_config.get("refresh_listing_mode") or "stale_only",
        "refresh_listing_ttl_days": int(bulk_config.get("refresh_listing_ttl_days") or 7),
        "alpha_incremental_enabled": bool(fetch_config.get("alpha_incremental_enabled", True)),
        "alpha_compact_days": int(fetch_config.get("alpha_compact_days") or 120),
        "min_delay_seconds": min_delay,
    }
    if symbol_whitelist_path:
        payload["symbol_whitelist_path"] = symbol_whitelist_path
        payload["symbol_whitelist_count"] = symbol_whitelist_count
    active = (
        ctx.session.query(BulkSyncJob)
        .filter(BulkSyncJob.status.in_("queued running paused".split()))
        .first()
    )
    if active:
        raise RuntimeError("bulk_sync_running")
    job = BulkSyncJob(
        status="queued",
        phase="listing_refresh",
        params=payload,
        batch_size=payload["batch_size"],
    )
    ctx.session.add(job)
    ctx.session.commit()
    ctx.session.refresh(job)
    _start_bulk_sync_worker(job.id)

    artifacts = {"bulk_job_id": job.id}
    if symbol_whitelist_path:
        artifacts.update(
            {
                "symbol_whitelist_path": symbol_whitelist_path,
                "symbol_whitelist_count": symbol_whitelist_count,
            }
        )
    while True:
        ctx.session.refresh(job)
        pending, running, completed = _bulk_job_counts(ctx.session, job)
        total = job.total_symbols or 0
        processed = job.processed_symbols or 0
        progress = None
        if total > 0:
            progress = min(max(processed / total, 0.0), 1.0)
        ctx.update(
            progress=progress,
            artifacts={
                **artifacts,
                "phase": job.phase,
                "pending": pending,
                "running": running,
                "completed": completed,
                "processed": processed,
                "total": total,
            },
        )
        if job.status in {"success", "failed", "canceled"}:
            break
        if ctx.run.status == "cancel_requested":
            job.cancel_requested = True
            ctx.session.commit()
        time.sleep(10)
    if job.status != "success":
        raise RuntimeError(f"bulk_sync_{job.status}")
    artifacts.update(
        {
            "status": job.status,
            "message": job.message,
            "error": job.error,
        }
    )
    return StepResult(artifacts=artifacts)


def step_listing_refresh(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    data_root = _resolve_data_root()
    bulk_config = load_bulk_auto_config(data_root)
    mode = (bulk_config.get("refresh_listing_mode") or "stale_only").strip().lower()
    ttl_days = int(bulk_config.get("refresh_listing_ttl_days") or 7)
    age_days, updated_at = _alpha_listing_age(data_root)
    artifacts = {
        "mode": mode,
        "ttl_days": ttl_days,
        "listing_age_days": age_days,
        "listing_updated_at": updated_at,
    }
    if mode == "never":
        raise StepSkip("listing_refresh_disabled", artifacts=artifacts)
    if mode == "stale_only" and age_days is not None and age_days < ttl_days:
        raise StepSkip("listing_fresh", artifacts=artifacts)
    summary = _refresh_alpha_listing()
    artifacts.update(summary)
    return StepResult(artifacts=artifacts)


def _read_progress_ratio(progress_path: Path) -> tuple[float | None, dict[str, Any] | None]:
    if not progress_path.exists():
        return None, None
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    total = payload.get("total")
    done = payload.get("done")
    if isinstance(total, (int, float)) and total:
        ratio = float(done or 0) / float(total)
        return min(max(ratio, 0.0), 1.0), payload
    return None, payload


def step_fundamentals_refresh(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    data_root = _resolve_data_root()
    today = datetime.now(ZoneInfo(settings.market_timezone)).date()
    cache_fresh, last_friday = _fundamentals_cache_fresh(data_root, today)
    log_dir = _ensure_log_dir(ctx.run.id)
    log_path = log_dir / "fundamentals_fetch.log"
    progress_path = log_dir / "fundamentals_progress.json"
    cancel_path = log_dir / "fundamentals_cancel.flag"
    status_path = data_root / "fundamentals" / "alpha" / "fundamentals_status.csv"

    settings_row = _get_or_create_settings(ctx.session)
    cmd_params = dict(params or {})
    missing_symbols: list[str] | None = None
    if settings_row.update_project_only:
        symbols, benchmarks = collect_active_project_symbols(ctx.session)
        if not symbols:
            raise StepSkip(
                "project_symbols_empty",
                artifacts={
                    "symbol_whitelist_count": 0,
                    "symbol_whitelist_benchmarks": benchmarks,
                },
            )
        missing_symbols = _fundamentals_missing_symbols(data_root, symbols, last_friday)
        if not missing_symbols:
            raise StepSkip(
                "fundamentals_complete",
                artifacts={
                    "cache_as_of": last_friday.isoformat(),
                    "symbol_whitelist_count": len(symbols),
                    "symbol_whitelist_benchmarks": benchmarks,
                    "symbol_missing_count": 0,
                },
            )
        symbol_path = log_dir / "fundamentals_missing_symbols.csv"
        write_symbol_list(symbol_path, missing_symbols)
        cmd_params["symbol_file"] = str(symbol_path)
        cmd_params["symbol_whitelist_count"] = len(symbols)
        cmd_params["symbol_missing_count"] = len(missing_symbols)
    else:
        symbol_file = cmd_params.get("symbol_file")
        if symbol_file:
            candidate_symbols = _read_snapshot_symbols(str(symbol_file))
            if candidate_symbols:
                missing_symbols = _fundamentals_missing_symbols(
                    data_root, candidate_symbols, last_friday
                )
                if not missing_symbols:
                    raise StepSkip(
                        "fundamentals_complete",
                        artifacts={
                            "cache_as_of": last_friday.isoformat(),
                            "symbol_whitelist_count": len(candidate_symbols),
                            "symbol_missing_count": 0,
                        },
                    )
                symbol_path = log_dir / "fundamentals_missing_symbols.csv"
                write_symbol_list(symbol_path, missing_symbols)
                cmd_params["symbol_file"] = str(symbol_path)
                cmd_params["symbol_whitelist_count"] = len(candidate_symbols)
                cmd_params["symbol_missing_count"] = len(missing_symbols)
        elif cache_fresh:
            raise StepSkip(
                "fundamentals_cache_fresh",
                artifacts={"cache_as_of": last_friday.isoformat()},
            )

    cmd = _build_fundamental_fetch_command(
        cmd_params,
        progress_path=progress_path,
        status_path=status_path,
        cancel_path=cancel_path,
        skip_lock=False,
    )

    with log_path.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            ratio, payload = _read_progress_ratio(progress_path)
            ctx.update(progress=ratio, artifacts={"progress": payload} if payload else None)
            if ctx.run.status == "cancel_requested":
                cancel_path.write_text("cancel", encoding="utf-8")
            time.sleep(10)
        code = proc.returncode
    if code != 0:
        raise RuntimeError(f"fundamentals_fetch_failed={code}")
    _write_fundamentals_cache_meta(data_root, last_friday)
    artifacts = {
        "progress_path": str(progress_path),
        "status_path": str(status_path),
    }
    if cmd_params.get("symbol_file"):
        artifacts["symbol_whitelist_path"] = cmd_params["symbol_file"]
        artifacts["symbol_whitelist_count"] = cmd_params.get("symbol_whitelist_count")
    return StepResult(artifacts=artifacts, log_path=str(log_path))


def step_pit_weekly(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    job = PitWeeklyJob(status="queued", params=params)
    ctx.session.add(job)
    ctx.session.commit()
    ctx.session.refresh(job)
    run_pit_weekly_job(job.id)
    with SessionLocal() as check_session:
        fresh = check_session.get(PitWeeklyJob, job.id)
        if not fresh:
            raise RuntimeError("pit_weekly_missing")
        if fresh.status != "success":
            raise RuntimeError(f"pit_weekly_{fresh.status}")
    return StepResult(
        artifacts={
            "job_id": job.id,
            "output_dir": fresh.output_dir,
            "snapshot_count": fresh.snapshot_count,
            "last_snapshot_path": fresh.last_snapshot_path,
        },
        log_path=fresh.log_path,
    )


def step_pit_fundamentals(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    settings_row = _get_or_create_settings(ctx.session)
    cmd_params = dict(params or {})
    project_symbols: list[str] | None = None
    project_benchmarks: list[str] | None = None
    if settings_row.update_project_only:
        symbols, benchmarks = collect_active_project_symbols(ctx.session)
        if not symbols:
            raise StepSkip(
                "project_symbols_empty",
                artifacts={
                    "symbol_whitelist_count": 0,
                    "symbol_whitelist_benchmarks": benchmarks,
                },
            )
        project_symbols = symbols
        project_benchmarks = benchmarks
    job = PitFundamentalJob(status="queued", params=cmd_params)
    ctx.session.add(job)
    ctx.session.commit()
    ctx.session.refresh(job)
    if project_symbols:
        log_dir = Path(settings.artifact_root) / f"pit_fundamental_job_{job.id}"
        symbol_path = log_dir / "project_symbols.csv"
        write_symbol_list(symbol_path, project_symbols)
        cmd_params["symbol_file"] = str(symbol_path)
        cmd_params["symbol_whitelist_count"] = len(project_symbols)
        cmd_params["symbol_whitelist_benchmarks"] = project_benchmarks or []
        job.params = cmd_params
        ctx.session.commit()
    run_pit_fundamental_job(job.id)
    with SessionLocal() as check_session:
        fresh = check_session.get(PitFundamentalJob, job.id)
        if not fresh:
            raise RuntimeError("pit_fundamentals_missing")
        if fresh.status != "success":
            raise RuntimeError(f"pit_fundamentals_{fresh.status}")
    return StepResult(
        artifacts={
            "job_id": job.id,
            "output_dir": fresh.output_dir,
            "snapshot_count": fresh.snapshot_count,
            "last_snapshot_path": fresh.last_snapshot_path,
        },
        log_path=fresh.log_path,
    )


def step_training_scoring(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    mode = (params.get("training_mode") or "skip").strip().lower()
    if mode == "skip":
        raise StepSkip("training_skipped")
    if mode == "factor":
        job = FactorScoreJob(project_id=ctx.run.project_id, status="queued", params=params)
        ctx.session.add(job)
        ctx.session.commit()
        ctx.session.refresh(job)
        run_factor_score_job(job.id)
        ctx.session.refresh(job)
        if job.status != "success":
            raise RuntimeError(f"factor_score_{job.status}")
        return StepResult(
            artifacts={"job_id": job.id, "scores_path": job.scores_path},
            log_path=job.log_path,
        )
    if mode != "ml":
        raise StepSkip("training_mode_unknown")
    overrides = params.get("train_overrides") or {}
    config = build_ml_config(ctx.session, ctx.run.project_id, overrides)
    job = MLTrainJob(project_id=ctx.run.project_id, status="queued", config=config)
    ctx.session.add(job)
    ctx.session.commit()
    ctx.session.refresh(job)
    run_ml_train(job.id)
    ctx.session.refresh(job)
    if job.status != "success":
        raise RuntimeError(f"ml_train_{job.status}")
    return StepResult(
        artifacts={
            "job_id": job.id,
            "scores_path": job.scores_path,
            "output_dir": job.output_dir,
        },
        log_path=job.log_path,
    )


def step_audit(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    asset_types = {"STOCK"}
    alpha_report = _audit_alpha_coverage(
        session=ctx.session,
        asset_types=asset_types,
        enqueue_missing=False,
        enqueue_missing_adjusted=False,
        sample_size=0,
    )
    trade_report = _audit_trade_coverage(
        asset_types=asset_types,
        benchmark=(params.get("benchmark") or "SPY").strip().upper(),
        vendor_preference=["Alpha"],
        start=None,
        end=None,
        sample_size=0,
        pit_dir=_resolve_data_root() / "universe" / "pit_weekly",
        fundamentals_root=_resolve_data_root() / "fundamentals" / "alpha",
        pit_fundamentals_dir=_resolve_data_root() / "factors" / "pit_weekly_fundamentals",
    )
    return StepResult(
        artifacts={
            "alpha_report": alpha_report,
            "trade_report": trade_report,
        }
    )


def step_decision_snapshot(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    settings_row = _get_or_create_settings(ctx.session)
    if not settings_row.auto_decision_snapshot:
        raise StepSkip("decision_snapshot_disabled")
    existing_snapshot_id = None
    existing_trade_run_id = None
    if isinstance(ctx.step.artifacts, dict):
        existing_snapshot_id = ctx.step.artifacts.get("decision_snapshot_id")
        existing_trade_run_id = ctx.step.artifacts.get("trade_run_id")
    algo_params = params.get("algorithm_parameters")
    if not isinstance(algo_params, dict):
        algo_params = {}
    result = generate_decision_snapshot(
        ctx.session,
        project_id=ctx.run.project_id,
        train_job_id=params.get("train_job_id"),
        pipeline_id=params.get("pipeline_id"),
        snapshot_date=params.get("snapshot_date"),
        algorithm_parameters=algo_params,
        preview=False,
    )
    summary = result.get("summary") or {}
    snapshot: DecisionSnapshot | None = None
    if existing_snapshot_id:
        try:
            snapshot = ctx.session.get(DecisionSnapshot, int(existing_snapshot_id))
        except Exception:
            snapshot = None
    if snapshot is None:
        snapshot = DecisionSnapshot(
            project_id=ctx.run.project_id,
            pipeline_id=params.get("pipeline_id"),
            train_job_id=params.get("train_job_id"),
            status="success",
            snapshot_date=summary.get("snapshot_date"),
            params={
                "project_id": ctx.run.project_id,
                "pipeline_id": params.get("pipeline_id"),
                "train_job_id": params.get("train_job_id"),
                "snapshot_date": summary.get("snapshot_date"),
                "algorithm_parameters": algo_params,
                "pretrade_run_id": ctx.run.id,
            },
            summary=summary,
            artifact_dir=result.get("artifact_dir"),
            summary_path=result.get("summary_path"),
            items_path=result.get("items_path"),
            filters_path=result.get("filters_path"),
            log_path=result.get("log_path"),
            started_at=datetime.utcnow(),
            ended_at=datetime.utcnow(),
        )
        ctx.session.add(snapshot)
        ctx.session.commit()
        ctx.session.refresh(snapshot)
    config = _resolve_project_config(ctx.session, ctx.run.project_id)
    version = _get_latest_version(ctx.session, ctx.run.project_id, PROJECT_CONFIG_TAG)
    strategy_snapshot = {
        "project_config_version_id": version.id if version else None,
        "project_config_hash": version.content_hash if version else None,
        "project_config_created_at": version.created_at.isoformat() if version else None,
        "backtest_params": config.get("backtest_params") if isinstance(config, dict) else None,
        "strategy": config.get("strategy") if isinstance(config, dict) else None,
        "signal_mode": config.get("signal_mode") if isinstance(config, dict) else None,
        "backtest_start": config.get("backtest_start") if isinstance(config, dict) else None,
        "backtest_end": config.get("backtest_end") if isinstance(config, dict) else None,
        "benchmark": config.get("benchmark") if isinstance(config, dict) else None,
    }
    trade_run: TradeRun | None = None
    if existing_trade_run_id:
        trade_run = ctx.session.get(TradeRun, int(existing_trade_run_id))
    if trade_run is None:
        trade_run = (
            ctx.session.query(TradeRun)
            .filter(
                TradeRun.project_id == ctx.run.project_id,
                TradeRun.decision_snapshot_id == snapshot.id,
            )
            .order_by(TradeRun.created_at.desc())
            .first()
        )
    if trade_run is None:
        trade_run = TradeRun(
            project_id=ctx.run.project_id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            status="queued",
            params={
                "pretrade_run_id": ctx.run.id,
                "strategy_snapshot": strategy_snapshot,
            },
        )
        ctx.session.add(trade_run)
        ctx.session.commit()
        ctx.session.refresh(trade_run)
    else:
        existing_params = dict(trade_run.params or {})
        if "strategy_snapshot" not in existing_params:
            existing_params["strategy_snapshot"] = strategy_snapshot
        if "pretrade_run_id" not in existing_params:
            existing_params["pretrade_run_id"] = ctx.run.id
        trade_run.params = existing_params
        ctx.session.commit()
    return StepResult(
        artifacts={
            "decision_snapshot": result.get("summary"),
            "decision_snapshot_path": result.get("summary_path"),
            "decision_snapshot_id": snapshot.id if snapshot else None,
            "trade_run_id": trade_run.id if trade_run else None,
        },
        log_path=result.get("log_path"),
    )


def step_bridge_gate(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    settings_row = _get_or_create_settings(ctx.session)
    bridge_root = _resolve_bridge_root()

    heartbeat_ttl = _coerce_ttl(settings_row.bridge_heartbeat_ttl_seconds, 60)
    account_ttl = _coerce_ttl(settings_row.bridge_account_ttl_seconds, 300)
    positions_ttl = _coerce_ttl(settings_row.bridge_positions_ttl_seconds, 300)
    quotes_ttl = _coerce_ttl(settings_row.bridge_quotes_ttl_seconds, 60)

    checks = {
        "heartbeat": _bridge_payload_check(
            bridge_root,
            filename="lean_bridge_status.json",
            ttl_seconds=heartbeat_ttl,
            timestamp_keys=["last_heartbeat", "updated_at"],
        ),
        "account": _bridge_payload_check(
            bridge_root,
            filename="account_summary.json",
            ttl_seconds=account_ttl,
            timestamp_keys=["updated_at", "refreshed_at"],
        ),
        "positions": _bridge_payload_check(
            bridge_root,
            filename="positions.json",
            ttl_seconds=positions_ttl,
            timestamp_keys=["updated_at", "refreshed_at"],
        ),
        "quotes": _bridge_payload_check(
            bridge_root,
            filename="quotes.json",
            ttl_seconds=quotes_ttl,
            timestamp_keys=["updated_at", "refreshed_at"],
        ),
    }

    missing = [key for key, item in checks.items() if item.get("missing")]
    stale = [
        key
        for key, item in checks.items()
        if not item.get("missing") and not item.get("ok")
    ]
    gate = {
        "ok": not missing and not stale,
        "missing": missing,
        "stale": stale,
        "checks": checks,
    }
    ctx.update(artifacts={"bridge_gate": gate})
    if not gate["ok"]:
        raise RuntimeError("bridge_gate_failed")
    return StepResult(artifacts={"bridge_gate": gate})


def step_trade_execute(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    trade_run_id = None
    if isinstance(ctx.step.artifacts, dict):
        trade_run_id = ctx.step.artifacts.get("trade_run_id")
    if trade_run_id is None:
        raise StepSkip("trade_run_missing")
    dry_run = bool(params.get("dry_run", False))
    force = bool(params.get("force", False))
    result = execute_trade_run(int(trade_run_id), dry_run=dry_run, force=force)
    return StepResult(
        artifacts={
            "trade_execute": {
                "run_id": result.run_id,
                "status": result.status,
            }
        }
    )


def step_market_snapshot(ctx: StepContext, params: dict[str, Any]) -> StepResult:
    config = _resolve_project_config(ctx.session, ctx.run.project_id)
    trade_cfg = config.get("trade") if isinstance(config.get("trade"), dict) else {}
    ttl_seconds = trade_cfg.get("market_snapshot_ttl_seconds")
    exclude_symbols_raw = trade_cfg.get("market_snapshot_exclude_symbols")
    try:
        ttl_seconds = int(ttl_seconds) if ttl_seconds is not None else 30
    except (TypeError, ValueError):
        ttl_seconds = 30

    decision_snapshot_id = None
    if isinstance(ctx.step.artifacts, dict):
        decision_snapshot_id = ctx.step.artifacts.get("decision_snapshot_id")
    if not decision_snapshot_id:
        query = (
            ctx.session.query(DecisionSnapshot)
            .filter(DecisionSnapshot.project_id == ctx.run.project_id)
        )
        if ctx.run.started_at:
            query = query.filter(DecisionSnapshot.created_at >= ctx.run.started_at)
        latest = query.order_by(DecisionSnapshot.created_at.desc()).first()
        if not latest:
            latest = (
                ctx.session.query(DecisionSnapshot)
                .filter(DecisionSnapshot.project_id == ctx.run.project_id)
                .order_by(DecisionSnapshot.created_at.desc())
                .first()
            )
        if latest:
            decision_snapshot_id = latest.id
    symbols = _build_snapshot_symbols(
        ctx.session,
        project_id=ctx.run.project_id,
        decision_snapshot_id=decision_snapshot_id,
    )
    excluded: set[str] = set()
    if exclude_symbols_raw:
        if isinstance(exclude_symbols_raw, (list, tuple, set)):
            candidates = list(exclude_symbols_raw)
        else:
            raw = str(exclude_symbols_raw)
            candidates = [item.strip() for item in raw.replace("\n", ",").split(",")]
        excluded = {_normalize_symbol(item) for item in candidates if _normalize_symbol(item)}
        if excluded:
            symbols = [symbol for symbol in symbols if _normalize_symbol(symbol) not in excluded]
    bridge_root = _resolve_bridge_root()
    position_symbols: list[str] = []
    positions_payload = read_positions(bridge_root)
    if isinstance(positions_payload, dict):
        items = positions_payload.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = _normalize_symbol(item.get("symbol"))
                if symbol:
                    position_symbols.append(symbol)
    symbols = merge_symbols(symbols, position_symbols)
    if excluded and symbols:
        symbols = [symbol for symbol in symbols if _normalize_symbol(symbol) not in excluded]
    if symbols:
        write_watchlist(
            resolve_watchlist_path(bridge_root),
            symbols,
            meta={
                "source": "pretrade",
                "project_id": ctx.run.project_id,
                "decision_snapshot_id": decision_snapshot_id,
            },
        )
    if not symbols:
        reason = "market_snapshot_all_excluded" if excluded else "market_snapshot_no_symbols"
        skip_artifacts: dict[str, Any] = {"decision_snapshot_id": decision_snapshot_id}
        if excluded:
            skip_artifacts["excluded_symbols"] = sorted(excluded)
        raise StepSkip(reason, artifacts=skip_artifacts)

    watchlist_path = _write_watchlist(symbols)
    ok, missing, stale_symbols = _quotes_ready(symbols, ttl_seconds)
    if ok:
        return StepResult(
            artifacts={
                "market_snapshot": {
                    "skipped": True,
                    "symbols": symbols,
                    "ttl_seconds": ttl_seconds,
                    "decision_snapshot_id": decision_snapshot_id,
                    "excluded_symbols": sorted(excluded),
                    "watchlist_path": str(watchlist_path),
                }
            }
        )

    failure_artifacts = {
        "market_snapshot": {
            "skipped": False,
            "symbols": symbols,
            "ttl_seconds": ttl_seconds,
            "decision_snapshot_id": decision_snapshot_id,
            "excluded_symbols": sorted(excluded),
            "watchlist_path": str(watchlist_path),
            "missing_symbols": sorted(missing),
            "stale_symbols": sorted(stale_symbols),
        }
    }
    if ctx.step is not None:
        existing = dict(ctx.step.artifacts or {})
        existing.update(failure_artifacts)
        ctx.step.artifacts = existing
        ctx.step.updated_at = datetime.utcnow()
        ctx.session.commit()

    errors = [f"{symbol}:missing" for symbol in missing] + [f"{symbol}:stale" for symbol in stale_symbols]
    error_message = "; ".join(errors) if errors else "market_snapshot_unavailable"
    update_ib_state(ctx.session, status="degraded", message=error_message, heartbeat=True)
    raise RuntimeError("market_snapshot_failed")


STEP_DEFS = [
    ("calendar_refresh", step_calendar_refresh),
    ("trading_day_check", step_trading_day_check),
    ("price_incremental", step_price_incremental),
    ("listing_refresh", step_listing_refresh),
    ("fundamentals_refresh", step_fundamentals_refresh),
    ("pit_weekly", step_pit_weekly),
    ("pit_fundamentals", step_pit_fundamentals),
    ("training_scoring", step_training_scoring),
    ("decision_snapshot", step_decision_snapshot),
    ("bridge_gate", step_bridge_gate),
    ("market_snapshot", step_market_snapshot),
    ("trade_execute", step_trade_execute),
    ("audit", step_audit),
]


def build_default_steps() -> list[dict[str, Any]]:
    return [
        {"key": key, "enabled": True, "params": {}} for key, _ in STEP_DEFS
    ]


def _normalize_step_plan(step_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps = list(step_plan)

    def _is_enabled(item: dict[str, Any]) -> bool:
        return bool(item.get("enabled", True))

    def _find_enabled_index(key: str) -> int | None:
        for idx, item in enumerate(steps):
            if not isinstance(item, dict):
                continue
            if str(item.get("key") or "").strip() != key:
                continue
            if _is_enabled(item):
                return idx
        return None

    trading_idx = _find_enabled_index("trading_day_check")
    price_idx = _find_enabled_index("price_incremental")
    if trading_idx is None or price_idx is None:
        return steps
    if trading_idx > price_idx:
        return steps

    trading_item = steps.pop(trading_idx)
    if trading_idx < price_idx:
        price_idx -= 1
    steps.insert(price_idx + 1, trading_item)
    return steps


def _build_step_plan(template: PreTradeTemplate | None) -> list[dict[str, Any]]:
    if template and isinstance(template.params, dict):
        steps = template.params.get("steps")
        if isinstance(steps, list):
            return _normalize_step_plan(steps)
    return _normalize_step_plan(build_default_steps())


def _create_steps(session, run: PreTradeRun, template: PreTradeTemplate | None) -> None:
    step_plan = _build_step_plan(template)
    order_index = 0
    for item in step_plan:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        enabled = bool(item.get("enabled", True))
        params = item.get("params") if isinstance(item.get("params"), dict) else None
        status = "queued" if enabled else "skipped"
        step = PreTradeStep(
            run_id=run.id,
            step_key=key,
            step_order=order_index,
            status=status,
            params=params,
        )
        order_index += 1
        session.add(step)
    session.commit()


def create_pretrade_run_for_project(
    session,
    *,
    project_id: int,
    template_id: int | None = None,
) -> PreTradeRun:
    template = session.get(PreTradeTemplate, template_id) if template_id else None
    run = PreTradeRun(project_id=project_id, status="queued", params={})
    session.add(run)
    session.commit()
    session.refresh(run)
    _create_steps(session, run, template)
    return run


def _load_step_handler(step_key: str) -> StepHandler | None:
    for key, handler in STEP_DEFS:
        if key == step_key:
            return handler
    return None


def _prepare_run_snapshot(run: PreTradeRun) -> dict[str, Any]:
    data_root = _resolve_data_root()
    alpha_rate = load_alpha_rate_config(data_root)
    alpha_fetch = load_alpha_fetch_config(data_root)
    bulk_auto = load_bulk_auto_config(data_root)
    snapshot = {
        "alpha_rate": {
            "max_rpm": alpha_rate.get("max_rpm"),
            "min_delay_seconds": alpha_rate.get("min_delay_seconds"),
            "effective_min_delay_seconds": alpha_rate.get("effective_min_delay_seconds"),
            "auto_tune": alpha_rate.get("auto_tune"),
            "path": alpha_rate.get("path"),
        },
        "alpha_fetch": {
            "alpha_incremental_enabled": alpha_fetch.get("alpha_incremental_enabled"),
            "alpha_compact_days": alpha_fetch.get("alpha_compact_days"),
            "path": alpha_fetch.get("path"),
        },
        "bulk_auto": bulk_auto,
    }
    params = dict(run.params or {})
    params.setdefault("snapshot", {})
    params["snapshot"].update(snapshot)
    return params


def _has_other_active_pretrade_runs(session, run_id: int) -> bool:
    return (
        session.query(PreTradeRun)
        .filter(
            PreTradeRun.status.in_(PRETRADE_ACTIVE_STATUSES),
            PreTradeRun.id != run_id,
        )
        .count()
        > 0
    )


def run_pretrade_run(run_id: int, resume_step_id: int | None = None) -> None:
    session = SessionLocal()
    lock: JobLock | None = None
    try:
        run = session.get(PreTradeRun, run_id)
        if not run:
            return
        if run.status in {"success", "failed", "canceled"}:
            return
        lock = JobLock("pretrade_checklist", _resolve_data_root())
        if not lock.acquire():
            if _has_other_active_pretrade_runs(session, run_id):
                run.status = "failed"
                run.message = "pretrade_lock_busy"
                run.ended_at = datetime.utcnow()
                session.commit()
                return
            lock = None
            run.message = "pretrade_lock_bypassed"
            session.commit()
        alpha_lock = JobLock("alpha_fetch", _resolve_data_root())
        if not alpha_lock.acquire():
            run.status = "failed"
            run.message = "alpha_lock_busy"
            run.ended_at = datetime.utcnow()
            session.commit()
            return
        alpha_lock.release()

        settings_row = _get_or_create_settings(session)
        deadline_at = _compute_deadline_at(run, settings_row)
        run.deadline_at = deadline_at
        run.status = "running"
        run.started_at = run.started_at or datetime.utcnow()
        run.params = _prepare_run_snapshot(run)
        session.commit()

        steps = (
            session.query(PreTradeStep)
            .filter(PreTradeStep.run_id == run_id)
            .order_by(PreTradeStep.step_order.asc())
            .all()
        )
        resume_reached = resume_step_id is None
        for step in steps:
            if run.status == "cancel_requested":
                step.status = "canceled"
                step.message = "run_canceled"
                step.ended_at = datetime.utcnow()
                session.commit()
                break
            if not resume_reached:
                if step.id == resume_step_id:
                    resume_reached = True
                else:
                    continue
            if step.status in {"success", "skipped"}:
                continue
            handler = _load_step_handler(step.step_key)
            if not handler:
                step.status = "skipped"
                step.message = "unknown_step"
                step.ended_at = datetime.utcnow()
                session.commit()
                continue
            retry_count = step.retry_count or 0
            while True:
                if run.status == "cancel_requested":
                    step.status = "canceled"
                    step.message = "run_canceled"
                    step.ended_at = datetime.utcnow()
                    session.commit()
                    break
                step.status = "running"
                step.started_at = step.started_at or datetime.utcnow()
                step.updated_at = datetime.utcnow()
                session.commit()
                ctx = StepContext(session=session, run=run, step=step)
                try:
                    result = handler(ctx, dict(step.params or {}))
                except StepSkip as exc:
                    step.status = "skipped"
                    step.message = exc.reason
                    step.progress = 1.0
                    step.artifacts = exc.artifacts or step.artifacts
                    step.ended_at = datetime.utcnow()
                    session.commit()
                    break
                except Exception as exc:
                    error_key = str(exc)
                    if step.step_key == "market_snapshot" and error_key == "market_snapshot_failed":
                        step.status = "failed"
                        step.message = "行情快照不可用"
                        step.ended_at = datetime.utcnow()
                        run.status = "failed"
                        run.message = "行情快照不可用"
                        run.ended_at = datetime.utcnow()
                        session.commit()
                        _notify_telegram(
                            settings_row,
                            f"PreTrade step failed: run={run_id} step={step.step_key} error={error_key}",
                        )
                        break
                    retry_count += 1
                    step.retry_count = retry_count
                    step.status = "failed"
                    step.message = error_key
                    step.ended_at = datetime.utcnow()
                    session.commit()
                    now = datetime.utcnow()
                    if _should_retry(now, deadline_at, settings_row, retry_count):
                        delay = _compute_retry_delay(settings_row, retry_count)
                        step.status = "queued"
                        step.next_retry_at = now + timedelta(seconds=delay)
                        step.ended_at = None
                        session.commit()
                        time.sleep(delay)
                        continue
                    _notify_telegram(
                        settings_row,
                        f"PreTrade step failed: run={run_id} step={step.step_key} error={exc}",
                    )
                    run.status = "failed"
                    run.message = f"step_failed:{step.step_key}"
                    run.ended_at = datetime.utcnow()
                    session.commit()
                    break
                else:
                    step.status = "success"
                    step.progress = 1.0
                    step.message = "success"
                    if result.artifacts:
                        step.artifacts = {
                            **(step.artifacts or {}),
                            **result.artifacts,
                        }
                    if result.log_path:
                        step.log_path = result.log_path
                    step.ended_at = datetime.utcnow()
                    session.commit()
                    break
            if run.status in {"failed", "canceled"}:
                break
        session.refresh(run)
        if run.status == "cancel_requested":
            run.status = "canceled"
            run.message = "canceled"
            run.ended_at = datetime.utcnow()
            session.commit()
        elif run.status == "running":
            run.status = "success"
            run.message = "success"
            run.ended_at = datetime.utcnow()
            session.commit()
            _notify_telegram(settings_row, f"PreTrade run success: run={run_id}")
        elif run.status == "failed":
            if deadline_at and datetime.utcnow() >= deadline_at:
                last_success = (
                    session.query(PreTradeRun)
                    .filter(
                        PreTradeRun.project_id == run.project_id,
                        PreTradeRun.status == "success",
                        PreTradeRun.id != run.id,
                    )
                    .order_by(PreTradeRun.created_at.desc())
                    .first()
                )
                if last_success:
                    run.fallback_used = True
                    run.fallback_run_id = last_success.id
                    run.message = f"fallback_to_run={last_success.id}"
                    session.commit()
    finally:
        if lock:
            lock.release()
        session.close()
