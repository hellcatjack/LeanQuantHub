from __future__ import annotations

import csv
from bisect import bisect_right
import threading
import json
import math
import re
import shutil
import time
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import func, or_

from app.db import SessionLocal, get_session
from app.models import BulkSyncJob, DataSyncJob, Dataset, UniverseMembership
from app.core.config import settings
from app.schemas import (
    BulkSyncCreate,
    BulkSyncOut,
    BulkSyncPageOut,
    DataSyncCreate,
    DataSyncBatchRequest,
    DataSyncOut,
    DataSyncPageOut,
    DataSyncQueueClearOut,
    DataSyncQueueClearRequest,
    DataSyncQueueRunOut,
    DataSyncQueueRunRequest,
    DataSyncSpeedOut,
    AlphaCoverageAuditOut,
    AlphaCoverageAuditRequest,
    AlphaDuplicateCleanupItem,
    AlphaDuplicateCleanupOut,
    AlphaDuplicateCleanupRequest,
    AlphaNameRepairOut,
    AlphaNameRepairRequest,
    AlphaNameRepairItem,
    TradeCoverageAuditOut,
    TradeCoverageAuditRequest,
    AlphaFetchConfigOut,
    AlphaFetchConfigUpdate,
    AlphaGapSummaryOut,
    AlphaRateConfigOut,
    AlphaRateConfigUpdate,
    TradingCalendarConfigOut,
    TradingCalendarConfigUpdate,
    TradingCalendarRefreshOut,
    TradingCalendarPreviewOut,
    TradingCalendarPreviewDay,
    BulkAutoConfigOut,
    BulkAutoConfigUpdate,
    DatasetCreate,
    DatasetDeleteOut,
    DatasetDeleteRequest,
    DatasetFetchOut,
    DatasetFetchRequest,
    DatasetListingFetchOut,
    DatasetListingFetchRequest,
    DatasetOut,
    DatasetPageOut,
    DatasetQualityOut,
    DatasetQualityScanOut,
    DatasetQualityScanRequest,
    DatasetSeriesOut,
    DatasetThemeCoverageOut,
    DatasetThemeFetchOut,
    DatasetThemeFetchRequest,
    DatasetUpdate,
)
from app.services.audit_log import record_audit
from app.services.alpha_rate import (
    DEFAULT_RATE_LIMIT_SLEEP,
    load_alpha_rate_config,
    note_alpha_request,
    write_alpha_rate_config,
)
from app.services.alpha_fetch import (
    DEFAULT_ALPHA_COMPACT_DAYS,
    DEFAULT_ALPHA_INCREMENTAL_ENABLED,
    load_alpha_fetch_config,
    write_alpha_fetch_config,
)
from app.services.bulk_auto import load_bulk_auto_config, write_bulk_auto_config
from app.services.project_symbols import collect_active_project_symbols, write_symbol_list
from app.services.trading_calendar import (
    load_trading_calendar_config,
    load_trading_calendar_meta,
    load_trading_days,
    trading_calendar_csv_path,
    trading_calendar_overrides_path,
    write_trading_calendar_config,
)
from app.services.job_lock import JobLock

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

MAX_PAGE_SIZE = 200
ACTIVE_SYNC_STATUSES = {"queued", "running", "rate_limited"}
STOOQ_RATE_LIMIT_WINDOW = timedelta(hours=24)
_stooq_rate_limited_until: datetime | None = None

YAHOO_RATE_LIMIT_WINDOW = timedelta(hours=6)
_yahoo_rate_limited_until: datetime | None = None

_alpha_rate_limited_until: datetime | None = None
_alpha_last_request_at: float | None = None

ALPHA_ONLY_PRICES = True

RETRY_IMMEDIATE_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 10
RETRY_MAX_ATTEMPTS = 8
RETRY_MAX_BACKOFF_SECONDS = 24 * 60 * 60
MAX_BULK_ERRORS = 200

SYNC_QUEUE_LOCK = threading.Lock()
SYNC_QUEUE_RUNNING = False

BULK_SYNC_LOCK = threading.Lock()
BULK_SYNC_RUNNING: set[int] = set()


def _coerce_pagination(page: int, page_size: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


def _compute_retry_delay(retry_count: int, min_delay: int | None = None) -> int:
    if retry_count <= RETRY_IMMEDIATE_ATTEMPTS:
        delay = RETRY_BASE_DELAY_SECONDS
    else:
        exponent = retry_count - RETRY_IMMEDIATE_ATTEMPTS
        delay = RETRY_BASE_DELAY_SECONDS * (2**exponent)
    if min_delay is not None:
        delay = max(delay, min_delay)
    return int(min(delay, RETRY_MAX_BACKOFF_SECONDS))


def _wait_alpha_rate_slot() -> None:
    global _alpha_last_request_at
    config = load_alpha_rate_config(_get_data_root())
    min_delay = max(float(config.get("effective_min_delay_seconds") or 0.0), 0.0)
    now = time.monotonic()
    if _alpha_last_request_at is not None:
        elapsed = now - _alpha_last_request_at
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)


def _note_alpha_request(rate_limited: bool = False) -> None:
    global _alpha_last_request_at
    _alpha_last_request_at = time.monotonic()
    note_alpha_request(_get_data_root(), rate_limited=rate_limited)


def _default_queue_min_delay() -> float:
    config = load_alpha_rate_config(_get_data_root())
    return max(float(config.get("effective_min_delay_seconds") or 0.0), 0.0)


def _acquire_alpha_fetch_lock() -> JobLock | None:
    lock = JobLock("alpha_fetch", _get_data_root())
    if not lock.acquire():
        return None
    return lock


def _schedule_retry(
    session,
    job: DataSyncJob,
    reason: str,
    min_delay: int | None = None,
    status: str = "queued",
    spawn_thread: bool = True,
) -> bool:
    job.retry_count = (job.retry_count or 0) + 1
    if job.retry_count > RETRY_MAX_ATTEMPTS:
        job.status = "failed"
        job.message = f"{reason}; max_retries"
        job.ended_at = datetime.utcnow()
        record_audit(
            session,
            action="data.sync.failed",
            resource_type="data_sync_job",
            resource_id=job.id,
            detail={"dataset_id": job.dataset_id, "error": job.message},
        )
        session.commit()
        return False
    delay = _compute_retry_delay(job.retry_count, min_delay=min_delay)
    queued_at = datetime.utcnow()
    job.status = status
    job.next_retry_at = queued_at + timedelta(seconds=delay)
    job.created_at = queued_at
    job.message = (
        f"reason={reason}; retry_in={delay}s; retry_count={job.retry_count}; "
        f"queued_at={queued_at.isoformat()}"
    )
    session.commit()
    record_audit(
        session,
        action="data.sync.retry",
        resource_type="data_sync_job",
        resource_id=job.id,
        detail={
            "dataset_id": job.dataset_id,
            "retry_in": delay,
            "reason": reason,
            "retry_count": job.retry_count,
            "queued_at": queued_at.isoformat(),
        },
    )

    if spawn_thread:
        def _runner():
            time.sleep(delay)
            _start_sync_queue_worker(0, _default_queue_min_delay())

        threading.Thread(target=_runner, daemon=True).start()
    return True


def _set_job_stage(
    session, job: DataSyncJob, stage: str, progress: float | None = None
) -> None:
    if job.status != "running":
        return
    message = f"stage={stage}"
    if progress is not None:
        message = f"{message}; progress={progress:.2f}"
    job.message = message
    session.commit()


def _count_pending_sync_jobs(session) -> int:
    now = datetime.utcnow()
    return (
        session.query(DataSyncJob)
        .filter(
            DataSyncJob.status.in_(("queued", "rate_limited")),
            or_(DataSyncJob.next_retry_at.is_(None), DataSyncJob.next_retry_at <= now),
        )
        .count()
    )


def _start_sync_queue_worker(max_jobs: int, min_delay_seconds: float) -> bool:
    global SYNC_QUEUE_RUNNING
    with SYNC_QUEUE_LOCK:
        if SYNC_QUEUE_RUNNING:
            return False
        SYNC_QUEUE_RUNNING = True

    def _worker():
        global SYNC_QUEUE_RUNNING
        queue_lock = JobLock("data_sync_queue", _get_data_root())
        if not queue_lock.acquire():
            with SYNC_QUEUE_LOCK:
                SYNC_QUEUE_RUNNING = False
            return
        processed = 0
        try:
            while True:
                with get_session() as session:
                    now = datetime.utcnow()
                    job = (
                        session.query(DataSyncJob)
                        .filter(
                            DataSyncJob.status.in_(("queued", "rate_limited")),
                            or_(
                                DataSyncJob.next_retry_at.is_(None),
                                DataSyncJob.next_retry_at <= now,
                            ),
                        )
                        .order_by(DataSyncJob.created_at.asc())
                        .first()
                    )
                    if not job:
                        break
                    job_id = job.id

                run_data_sync(job_id, spawn_retry_thread=False)
                processed += 1
                if max_jobs and processed >= max_jobs:
                    break
                if min_delay_seconds > 0:
                    time.sleep(min_delay_seconds)
        finally:
            queue_lock.release()
            with SYNC_QUEUE_LOCK:
                SYNC_QUEUE_RUNNING = False

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _bulk_job_range(job: BulkSyncJob) -> tuple[datetime, datetime] | None:
    if not job.enqueued_start_at:
        return None
    end = job.enqueued_end_at or datetime.utcnow()
    return job.enqueued_start_at, end


def _bulk_job_counts(session, job: BulkSyncJob) -> tuple[int | None, int | None, int | None]:
    window = _bulk_job_range(job)
    if not window:
        return None, None, None
    start, end = window
    base = session.query(DataSyncJob).filter(
        DataSyncJob.created_at >= start,
        DataSyncJob.created_at <= end,
    )
    pending = base.filter(DataSyncJob.status.in_(("queued", "rate_limited"))).count()
    running = base.filter(DataSyncJob.status == "running").count()
    completed = base.filter(DataSyncJob.ended_at.isnot(None)).count()
    return pending, running, completed


def _alpha_listing_age(data_root: Path) -> tuple[int | None, str | None]:
    candidate_paths = [
        data_root / "universe" / "alpha_symbol_life.csv",
        data_root / "universe" / "alpha_listing_status_active_latest.csv",
        data_root / "universe" / "alpha_listing_status_delisted_latest.csv",
    ]
    mtimes: list[float] = []
    for path in candidate_paths:
        if path.exists():
            try:
                mtimes.append(path.stat().st_mtime)
            except OSError:
                continue
    if not mtimes:
        return None, None
    latest_mtime = max(mtimes)
    updated_at = datetime.utcfromtimestamp(latest_mtime).isoformat()
    age_days = int((datetime.utcnow().timestamp() - latest_mtime) // 86400)
    return max(age_days, 0), updated_at


def _build_alpha_gap_summary(session) -> dict[str, Any]:
    latest_complete = _latest_complete_business_day()
    data_root = _get_data_root()
    age_days, updated_at = _alpha_listing_age(data_root)
    datasets = (
        session.query(Dataset)
        .filter(func.lower(Dataset.vendor) == "alpha")
        .filter(func.lower(Dataset.frequency) == "daily")
        .all()
    )
    total = len(datasets)
    missing_coverage = 0
    with_coverage = 0
    up_to_date = 0
    gap_0_30 = 0
    gap_31_120 = 0
    gap_120_plus = 0
    for dataset in datasets:
        coverage_end = _parse_date(dataset.coverage_end)
        if not coverage_end:
            missing_coverage += 1
            continue
        with_coverage += 1
        gap = (latest_complete - coverage_end).days
        if gap <= 0:
            up_to_date += 1
            gap_0_30 += 1
            continue
        if gap <= 30:
            gap_0_30 += 1
        elif gap <= 120:
            gap_31_120 += 1
        else:
            gap_120_plus += 1
    return {
        "latest_complete": latest_complete.isoformat(),
        "total": total,
        "with_coverage": with_coverage,
        "missing_coverage": missing_coverage,
        "up_to_date": up_to_date,
        "gap_0_30": gap_0_30,
        "gap_31_120": gap_31_120,
        "gap_120_plus": gap_120_plus,
        "listing_updated_at": updated_at,
        "listing_age_days": age_days,
    }


def _bulk_append_error(errors: list[dict], phase: str, message: str) -> list[dict]:
    if len(errors) >= MAX_BULK_ERRORS:
        return errors
    errors.append(
        {
            "ts": datetime.utcnow().isoformat(),
            "phase": phase,
            "message": message,
        }
    )
    return errors


def _bulk_check_control(session, job: BulkSyncJob, errors: list[dict]) -> bool:
    session.refresh(job)
    if job.cancel_requested:
        job.status = "canceled"
        job.phase = "canceled"
        job.ended_at = datetime.utcnow()
        job.cancel_requested = False
        job.pause_requested = False
        job.errors = errors
        session.commit()
        return True
    if job.pause_requested:
        job.status = "paused"
        job.phase = job.phase or "paused"
        job.pause_requested = False
        job.errors = errors
        session.commit()
        return True
    return False


def _start_bulk_sync_worker(job_id: int) -> bool:
    with BULK_SYNC_LOCK:
        if job_id in BULK_SYNC_RUNNING:
            return False
        BULK_SYNC_RUNNING.add(job_id)

    def _worker():
        try:
            _run_bulk_sync_job(job_id)
        finally:
            with BULK_SYNC_LOCK:
                BULK_SYNC_RUNNING.discard(job_id)

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _load_bulk_symbols(
    status_filter: str,
    asset_types: set[str],
) -> list[dict[str, str]]:
    rows = _load_listing_rows(_resolve_listing_paths(None))
    symbols: list[dict[str, str]] = []
    for row in rows:
        symbol = _normalize_symbol(row.get("symbol", "")).upper()
        if not symbol or symbol == "UNKNOWN":
            continue
        row_status = (row.get("status") or "").strip().lower()
        if status_filter != "all" and row_status != status_filter:
            continue
        asset_type = (row.get("assetType") or "").strip().upper() or "UNKNOWN"
        if asset_types and asset_type not in asset_types:
            continue
        symbols.append(
            {
                "symbol": symbol,
                "assetType": asset_type,
            }
        )
    symbols.sort(key=lambda item: item["symbol"])
    return symbols


def _load_symbol_whitelist(params: dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    raw = params.get("symbol_whitelist")
    if isinstance(raw, (list, tuple, set)):
        symbols.update({str(item).strip().upper() for item in raw if str(item).strip()})
    elif isinstance(raw, str) and raw.strip():
        parts = [item.strip() for item in raw.replace("\n", ",").split(",")]
        symbols.update({item.upper() for item in parts if item})

    path_value = params.get("symbol_whitelist_path")
    if isinstance(path_value, str) and path_value.strip():
        path = Path(path_value).expanduser()
        try:
            with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames and "symbol" in reader.fieldnames:
                    for row in reader:
                        symbol = (row.get("symbol") or "").strip().upper()
                        if symbol:
                            symbols.add(symbol)
                else:
                    handle.seek(0)
                    for line in handle:
                        symbol = line.strip().upper()
                        if symbol and symbol != "SYMBOL":
                            symbols.add(symbol)
        except OSError:
            return symbols
    return symbols


def _alpha_exclude_symbols_path(data_root: Path) -> Path:
    return data_root / "universe" / "alpha_exclude_symbols.csv"


def _load_alpha_exclude_symbols(data_root: Path) -> dict[str, str]:
    path = _alpha_exclude_symbols_path(data_root)
    if not path.exists():
        return {}
    excluded: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and "symbol" in reader.fieldnames:
                for row in reader:
                    symbol = (row.get("symbol") or "").strip().upper()
                    if not symbol:
                        continue
                    reason = (row.get("reason") or "").strip()
                    excluded[symbol] = reason
            else:
                handle.seek(0)
                for line in handle:
                    symbol = line.strip().upper()
                    if symbol and symbol != "SYMBOL":
                        excluded[symbol] = ""
    except OSError:
        return {}
    return excluded


def _append_alpha_exclude_symbol(data_root: Path, symbol: str, reason: str) -> None:
    cleaned = _normalize_symbol(symbol).upper()
    if not cleaned or cleaned == "UNKNOWN":
        return
    lock = JobLock("alpha_exclude_symbols", data_root)
    if not lock.acquire():
        return
    try:
        existing = _load_alpha_exclude_symbols(data_root)
        if cleaned in existing:
            return
        path = _alpha_exclude_symbols_path(data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(["symbol", "reason", "updated_at"])
            writer.writerow([cleaned, reason, datetime.utcnow().isoformat()])
    finally:
        lock.release()


def _run_bulk_sync_job(job_id: int) -> None:
    session = SessionLocal()
    bulk_lock: JobLock | None = None
    try:
        job = session.get(BulkSyncJob, job_id)
        if not job:
            return
        if job.status in {"success", "failed", "canceled"}:
            return
        bulk_lock = JobLock("bulk_sync", _get_data_root())
        if not bulk_lock.acquire():
            job.status = "blocked"
            job.message = "bulk_sync_lock_busy"
            job.ended_at = datetime.utcnow()
            record_audit(
                session,
                action="bulk_sync.blocked",
                resource_type="bulk_sync_job",
                resource_id=job_id,
                detail={"error": job.message},
            )
            session.commit()
            return
        errors = list(job.errors or [])
        params = job.params or {}
        status_filter = (params.get("status") or "all").strip().lower()
        batch_size = int(params.get("batch_size") or job.batch_size or 200)
        only_missing = bool(params.get("only_missing", True))
        auto_sync = bool(params.get("auto_sync", True))
        refresh_listing = bool(params.get("refresh_listing", True))
        refresh_listing_mode = (params.get("refresh_listing_mode") or "stale_only").strip().lower()
        refresh_listing_ttl_days = int(params.get("refresh_listing_ttl_days") or 7)
        alpha_incremental_enabled = bool(params.get("alpha_incremental_enabled", True))
        alpha_compact_days = int(params.get("alpha_compact_days") or DEFAULT_ALPHA_COMPACT_DAYS)
        min_delay_seconds = float(params.get("min_delay_seconds") or 0.9)

        write_alpha_fetch_config(
            {
                "alpha_incremental_enabled": alpha_incremental_enabled,
                "alpha_compact_days": alpha_compact_days,
            },
            _get_data_root(),
        )

        if not job.started_at:
            job.started_at = datetime.utcnow()
        job.status = "running"
        session.commit()

        if _bulk_check_control(session, job, errors):
            return

        if job.phase in {"queued", "listing_refresh"}:
            job.phase = "listing_refresh"
            listing_age_days, listing_updated_at = _alpha_listing_age(_get_data_root())
            refresh_reason = ""
            if not refresh_listing:
                refresh_reason = "disabled"
            elif refresh_listing_mode == "always":
                refresh_listing = True
                refresh_reason = "mode=always"
            elif refresh_listing_mode == "never":
                refresh_listing = False
                refresh_reason = "mode=never"
            else:
                if listing_age_days is None:
                    refresh_listing = True
                    refresh_reason = "missing_forced"
                else:
                    refresh_listing = listing_age_days >= max(refresh_listing_ttl_days, 1)
                    refresh_reason = "stale_only"
            job.message = (
                "refresh_listing; "
                f"mode={refresh_listing_mode}; "
                f"ttl_days={refresh_listing_ttl_days}; "
                f"listing_age_days={listing_age_days if listing_age_days is not None else 'none'}; "
                f"refresh={int(refresh_listing)}; "
                f"reason={refresh_reason}"
            )
            session.commit()
            if refresh_listing:
                try:
                    summary = _refresh_alpha_listing()
                except Exception as exc:
                    errors = _bulk_append_error(errors, "listing_refresh", str(exc))
                    job.errors = errors
                    job.error = str(exc)
                    session.commit()
                    raise
                job.message = (
                    f"listing_ok; total={summary.get('total', 0)}"
                    f"; active={summary.get('active', 0)}"
                    f"; delisted={summary.get('delisted', 0)}"
                    f"; mode={refresh_listing_mode}"
                    f"; ttl_days={refresh_listing_ttl_days}"
                    f"; listing_age_days={listing_age_days if listing_age_days is not None else 'none'}"
                    "; refresh=1"
                )
                job.errors = errors
                session.commit()

        if job.phase in {"listing_refresh", "enqueue"}:
            job.phase = "enqueue"
            job.batch_size = batch_size
            if job.enqueued_start_at is None:
                job.enqueued_start_at = datetime.utcnow()
            session.commit()

            data_root = _get_data_root()
            asset_types = {"STOCK", "ETF"}
            symbols = _load_bulk_symbols(status_filter, asset_types)
            whitelist = _load_symbol_whitelist(params)
            if whitelist:
                symbols = [item for item in symbols if item["symbol"] in whitelist]
            exclude_map = _load_alpha_exclude_symbols(data_root)
            if exclude_map:
                symbols = [item for item in symbols if item["symbol"] not in exclude_map]
            if not symbols:
                errors = _bulk_append_error(errors, "enqueue", "listing_empty")
                job.errors = errors
                job.error = "listing_empty"
                session.commit()
                raise RuntimeError("listing_empty")
            total_symbols = len(symbols)
            job.total_symbols = total_symbols
            session.commit()

            offset = job.offset or 0
            created = job.created_datasets or 0
            reused = job.reused_datasets or 0
            queued = job.queued_jobs or 0
            if job.queue_started_at is not None:
                _start_sync_queue_worker(0, min_delay_seconds)

            while offset < total_symbols:
                batch = symbols[offset : offset + batch_size]
                if not batch:
                    break
                if _bulk_check_control(session, job, errors):
                    return
                for item in batch:
                    symbol = item["symbol"]
                    try:
                        asset_type = item["assetType"]
                        asset_class = "ETF" if asset_type == "ETF" else "Equity"
                        source_path = f"alpha:{symbol.lower()}"
                        dataset_name = f"Alpha_{symbol}_Daily"
                        dataset = (
                            session.query(Dataset)
                            .filter(
                                Dataset.source_path == source_path,
                                Dataset.vendor == "Alpha",
                                Dataset.frequency == "daily",
                                Dataset.region == "US",
                            )
                            .first()
                        )
                        if not dataset:
                            dataset = (
                                session.query(Dataset)
                                .filter(Dataset.name == dataset_name)
                                .first()
                            )

                        if dataset and only_missing:
                            reused += 1
                            continue

                        if not dataset:
                            dataset = Dataset(
                                name=dataset_name,
                                vendor="Alpha",
                                asset_class=asset_class,
                                region="US",
                                frequency="daily",
                                source_path=source_path,
                            )
                            session.add(dataset)
                            session.flush()
                            created += 1
                            record_audit(
                                session,
                                action="dataset.create",
                                resource_type="dataset",
                                resource_id=dataset.id,
                                detail={"name": dataset.name, "source": "bulk_sync"},
                            )
                        else:
                            updated = False
                            if asset_class and dataset.asset_class != asset_class:
                                dataset.asset_class = asset_class
                                updated = True
                            if not dataset.frequency:
                                dataset.frequency = "daily"
                                updated = True
                            if not dataset.source_path and source_path:
                                dataset.source_path = source_path
                                updated = True
                            if updated:
                                dataset.updated_at = datetime.utcnow()
                                record_audit(
                                    session,
                                    action="dataset.update",
                                    resource_type="dataset",
                                    resource_id=dataset.id,
                                    detail={"source_path": source_path},
                                )

                        if auto_sync:
                            stored_source = _resolve_market_source(dataset, source_path)
                            date_column = (
                                "timestamp" if _is_alpha_source(stored_source) else "date"
                            )
                            active = (
                                session.query(DataSyncJob)
                                .filter(
                                    DataSyncJob.dataset_id == dataset.id,
                                    DataSyncJob.source_path == stored_source,
                                    DataSyncJob.date_column == date_column,
                                    DataSyncJob.reset_history.is_(False),
                                    DataSyncJob.status.in_(ACTIVE_SYNC_STATUSES),
                                )
                                .first()
                            )
                            if not active:
                                sync_job = DataSyncJob(
                                    dataset_id=dataset.id,
                                    source_path=stored_source,
                                    date_column=date_column,
                                    reset_history=False,
                                )
                                session.add(sync_job)
                                session.flush()
                                queued += 1
                                record_audit(
                                    session,
                                    action="data.sync.create",
                                    resource_type="data_sync_job",
                                    resource_id=sync_job.id,
                                    detail={
                                        "dataset_id": dataset.id,
                                        "source_path": stored_source,
                                    },
                                )
                    except Exception as exc:
                        errors = _bulk_append_error(
                            errors,
                            "enqueue",
                            f"{symbol}: {exc}",
                        )
                offset += len(batch)
                job.offset = offset
                job.processed_symbols = offset
                job.created_datasets = created
                job.reused_datasets = reused
                job.queued_jobs = queued
                job.errors = errors
                session.commit()
                if job.queue_started_at is None:
                    job.queue_started_at = datetime.utcnow()
                    session.commit()
                _start_sync_queue_worker(0, min_delay_seconds)
            job.enqueued_end_at = datetime.utcnow()
            job.phase = "syncing"
            session.commit()

        if job.phase == "syncing":
            _start_sync_queue_worker(0, min_delay_seconds)
            while True:
                if _bulk_check_control(session, job, errors):
                    return
                session.refresh(job)
                if job.status in {"failed", "canceled"}:
                    return
                pending, running, _ = _bulk_job_counts(session, job)
                if pending == 0 and running == 0:
                    job.status = "success"
                    job.phase = "done"
                    job.queue_ended_at = datetime.utcnow()
                    job.ended_at = datetime.utcnow()
                    job.errors = errors
                    session.commit()
                    return
                session.commit()
                time.sleep(10)
    except Exception as exc:
        job = session.get(BulkSyncJob, job_id)
        if job:
            errors = list(job.errors or [])
            errors = _bulk_append_error(errors, job.phase or "failed", str(exc))
            job.status = "failed"
            job.phase = job.phase or "failed"
            job.error = str(exc)
            job.errors = errors
            job.ended_at = datetime.utcnow()
            session.commit()
    finally:
        if bulk_lock:
            bulk_lock.release()
        session.close()


@router.get("", response_model=list[DatasetOut])
def list_datasets():
    with get_session() as session:
        return session.query(Dataset).order_by(Dataset.updated_at.desc()).all()


@router.get("/page", response_model=DatasetPageOut)
def list_datasets_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(Dataset).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size)
        total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
        if safe_page > total_pages:
            safe_page = total_pages
            offset = (safe_page - 1) * safe_page_size
        items = (
            session.query(Dataset)
            .order_by(Dataset.updated_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return DatasetPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/sync-jobs", response_model=list[DataSyncOut])
def list_sync_jobs():
    with get_session() as session:
        return session.query(DataSyncJob).order_by(DataSyncJob.created_at.desc()).all()


@router.get("/sync-jobs/page", response_model=DataSyncPageOut)
def list_sync_jobs_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(DataSyncJob).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size)
        total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
        if safe_page > total_pages:
            safe_page = total_pages
            offset = (safe_page - 1) * safe_page_size
        jobs = (
            session.query(DataSyncJob)
            .order_by(DataSyncJob.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        items = []
        for job in jobs:
            dataset = session.get(Dataset, job.dataset_id)
            out = DataSyncOut.model_validate(job, from_attributes=True)
            out.dataset_name = dataset.name if dataset else None
            items.append(out)
        return DataSyncPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/sync-jobs/speed", response_model=DataSyncSpeedOut)
def get_sync_speed(
    window_seconds: int = Query(60, ge=10, le=600),
):
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window_seconds)
    with get_session() as session:
        base = session.query(DataSyncJob).filter(
            func.lower(DataSyncJob.source_path).like("alpha:%")
        )
        completed = (
            base.filter(
                DataSyncJob.ended_at.isnot(None),
                DataSyncJob.ended_at >= window_start,
            )
            .count()
        )
        running = base.filter(DataSyncJob.status == "running").count()
        pending = base.filter(DataSyncJob.status.in_(("queued", "rate_limited"))).count()

    rate_per_min = completed * 60.0 / window_seconds
    config = load_alpha_rate_config(_get_data_root())
    return DataSyncSpeedOut(
        window_seconds=window_seconds,
        completed=completed,
        rate_per_min=rate_per_min,
        running=running,
        pending=pending,
        target_rpm=float(config.get("max_rpm") or 0.0) or None,
        effective_min_delay_seconds=float(config.get("effective_min_delay_seconds") or 0.0)
        or None,
    )


@router.get("/alpha-rate", response_model=AlphaRateConfigOut)
def get_alpha_rate_config():
    config = load_alpha_rate_config(_get_data_root())
    return AlphaRateConfigOut(**config)


@router.post("/alpha-rate", response_model=AlphaRateConfigOut)
def update_alpha_rate_config(payload: AlphaRateConfigUpdate):
    config = write_alpha_rate_config(payload.model_dump(), _get_data_root())
    return AlphaRateConfigOut(**config)


@router.get("/alpha-fetch-config", response_model=AlphaFetchConfigOut)
def get_alpha_fetch_config():
    config = load_alpha_fetch_config(_get_data_root())
    return AlphaFetchConfigOut(**config)


@router.post("/alpha-fetch-config", response_model=AlphaFetchConfigOut)
def update_alpha_fetch_config(payload: AlphaFetchConfigUpdate):
    config = write_alpha_fetch_config(payload.model_dump(), _get_data_root())
    return AlphaFetchConfigOut(**config)


@router.get("/bulk-auto-config", response_model=BulkAutoConfigOut)
def get_bulk_auto_config():
    config = load_bulk_auto_config(_get_data_root())
    return BulkAutoConfigOut(**config)


@router.post("/bulk-auto-config", response_model=BulkAutoConfigOut)
def update_bulk_auto_config(payload: BulkAutoConfigUpdate):
    config = write_bulk_auto_config(payload.model_dump(), _get_data_root())
    return BulkAutoConfigOut(**config)


def _merge_trading_calendar_config(
    config: dict[str, Any], meta: dict[str, Any], data_root: Path
) -> TradingCalendarConfigOut:
    exchange = str(config.get("exchange") or "")
    calendar_path = trading_calendar_csv_path(data_root, exchange) if exchange else None
    overrides_path = trading_calendar_overrides_path(data_root)
    return TradingCalendarConfigOut(
        source=str(config.get("source") or "auto"),
        config_source=str(config.get("config_source") or "default"),
        exchange=str(config.get("exchange") or "XNYS"),
        start_date=str(config.get("start_date") or ""),
        end_date=str(config.get("end_date") or ""),
        refresh_days=int(config.get("refresh_days") or 0),
        override_enabled=bool(config.get("override_enabled")),
        updated_at=config.get("updated_at"),
        path=str(config.get("path") or ""),
        calendar_source=meta.get("source"),
        calendar_exchange=meta.get("exchange"),
        calendar_start=meta.get("start_date"),
        calendar_end=meta.get("end_date"),
        calendar_generated_at=meta.get("generated_at"),
        calendar_sessions=meta.get("sessions"),
        calendar_path=str(calendar_path) if calendar_path else None,
        overrides_path=str(overrides_path),
        overrides_applied=meta.get("overrides_applied"),
    )


@router.get("/trading-calendar", response_model=TradingCalendarConfigOut)
def get_trading_calendar_config():
    data_root = _get_data_root()
    config = load_trading_calendar_config(data_root)
    meta = load_trading_calendar_meta(data_root)
    return _merge_trading_calendar_config(config, meta, data_root)


@router.post("/trading-calendar", response_model=TradingCalendarConfigOut)
def update_trading_calendar_config(payload: TradingCalendarConfigUpdate):
    data_root = _get_data_root()
    config = write_trading_calendar_config(payload.model_dump(), data_root)
    meta = load_trading_calendar_meta(data_root)
    return _merge_trading_calendar_config(config, meta, data_root)


@router.post("/trading-calendar/refresh", response_model=TradingCalendarRefreshOut)
def refresh_trading_calendar():
    data_root = _get_data_root()
    config = load_trading_calendar_config(data_root)
    log_dir = Path(settings.artifact_root) / "trading_calendar"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"refresh_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.log"
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
        raise HTTPException(
            status_code=500,
            detail=f"trading_calendar_refresh_failed log={log_path}",
        )
    meta = load_trading_calendar_meta(data_root)
    merged = _merge_trading_calendar_config(config, meta, data_root)
    return TradingCalendarRefreshOut(
        status="success",
        log_path=str(log_path),
        return_code=proc.returncode,
        calendar=merged,
    )


@router.get("/trading-calendar/preview", response_model=TradingCalendarPreviewOut)
def get_trading_calendar_preview(
    recent: int = Query(10, ge=1, le=60),
    upcoming: int = Query(10, ge=1, le=60),
    month: str | None = None,
):
    data_root = _get_data_root()
    adjusted_dir = data_root / "curated_adjusted"
    vendor_preference = ["Alpha"] if ALPHA_ONLY_PRICES else ["Lean", "Alpha"]
    days, info = load_trading_days(data_root, adjusted_dir, "SPY", vendor_preference)
    if not days:
        raise HTTPException(status_code=500, detail="交易日历为空")
    timezone_name = "America/New_York"
    tz = ZoneInfo(timezone_name)
    today = datetime.now(tz).date()
    idx = bisect_right(days, today) - 1
    latest_day = days[idx] if idx >= 0 else None
    next_index = idx + 1
    next_day = days[next_index] if 0 <= next_index < len(days) else None
    recent_start = max(0, idx - recent + 1)
    recent_days = days[recent_start : idx + 1] if idx >= 0 else []
    upcoming_start = bisect_right(days, today)
    upcoming_days = days[upcoming_start : upcoming_start + upcoming]
    if month:
        parts = month.split("-")
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="invalid month format")
        try:
            year = int(parts[0])
            month_num = int(parts[1])
            month_start = date(year, month_num, 1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid month value") from exc
    else:
        month_start = date(today.year, today.month, 1)
    month_label = f"{month_start.year:04d}-{month_start.month:02d}"
    next_month = (
        date(month_start.year + 1, 1, 1)
        if month_start.month == 12
        else date(month_start.year, month_start.month + 1, 1)
    )
    month_end = next_month - timedelta(days=1)
    grid_start = month_start - timedelta(days=month_start.weekday())
    grid_end = month_end + timedelta(days=(6 - month_end.weekday()))
    day_set = set(days)
    month_days: list[TradingCalendarPreviewDay] = []
    cursor = grid_start
    while cursor <= grid_end:
        month_days.append(
            TradingCalendarPreviewDay(
                date=cursor.isoformat(),
                weekday=cursor.weekday(),
                is_trading=cursor in day_set,
                in_month=cursor.month == month_start.month,
            )
        )
        cursor += timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    week_days: list[TradingCalendarPreviewDay] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        week_days.append(
            TradingCalendarPreviewDay(
                date=day.isoformat(),
                weekday=day.weekday(),
                is_trading=day in day_set,
            )
        )
    return TradingCalendarPreviewOut(
        timezone=timezone_name,
        as_of_date=today.isoformat(),
        month=month_label,
        latest_trading_day=latest_day.isoformat() if latest_day else None,
        next_trading_day=next_day.isoformat() if next_day else None,
        recent_trading_days=[day.isoformat() for day in recent_days],
        upcoming_trading_days=[day.isoformat() for day in upcoming_days],
        week_days=week_days,
        month_days=month_days,
        calendar_source=info.get("calendar_source"),
        overrides_applied=info.get("overrides_applied"),
        calendar_sessions=info.get("calendar_sessions"),
        calendar_start=info.get("calendar_start"),
        calendar_end=info.get("calendar_end"),
    )


@router.get("/alpha-gap-summary", response_model=AlphaGapSummaryOut)
def get_alpha_gap_summary():
    with get_session() as session:
        summary = _build_alpha_gap_summary(session)
    return AlphaGapSummaryOut(**summary)


@router.post("/actions/audit-alpha", response_model=AlphaCoverageAuditOut)
def audit_alpha_coverage(
    payload: AlphaCoverageAuditRequest = AlphaCoverageAuditRequest(),
):
    asset_types = _normalize_asset_types(payload.asset_types)
    sample_size = max(int(payload.sample_size or 0), 0)
    with get_session() as session:
        result = _audit_alpha_coverage(
            session=session,
            asset_types=asset_types,
            enqueue_missing=bool(payload.enqueue_missing),
            enqueue_missing_adjusted=bool(payload.enqueue_missing_adjusted),
            sample_size=sample_size,
        )
        session.commit()
    return AlphaCoverageAuditOut(**result)


@router.post("/actions/audit-trade", response_model=TradeCoverageAuditOut)
def audit_trade_coverage(
    payload: TradeCoverageAuditRequest = TradeCoverageAuditRequest(),
):
    asset_types = _normalize_asset_types(payload.asset_types)
    vendor_preference = payload.vendor_preference or ["Alpha"]
    sample_size = max(int(payload.sample_size or 0), 0)
    start = _parse_date_value(payload.start)
    end = _parse_date_value(payload.end)
    data_root = _get_data_root()
    pit_dir = _resolve_path(payload.pit_dir) if payload.pit_dir else data_root / "universe" / "pit_weekly"
    fundamentals_dir = (
        _resolve_path(payload.fundamentals_dir)
        if payload.fundamentals_dir
        else data_root / "fundamentals" / "alpha"
    )
    pit_fundamentals_dir = (
        _resolve_path(payload.pit_fundamentals_dir)
        if payload.pit_fundamentals_dir
        else data_root / "factors" / "pit_weekly_fundamentals"
    )
    result = _audit_trade_coverage(
        asset_types=asset_types,
        benchmark=(payload.benchmark or "SPY").strip().upper(),
        vendor_preference=[item.strip() for item in vendor_preference if item and item.strip()],
        start=start,
        end=end,
        sample_size=sample_size,
        pit_dir=pit_dir,
        fundamentals_root=fundamentals_dir,
        pit_fundamentals_dir=pit_fundamentals_dir,
    )
    with get_session() as session:
        record_audit(
            session,
            action="data.audit.trade",
            resource_type="data_audit",
            resource_id=None,
            detail={
                "report_dir": result.get("report_dir"),
                "price_missing": result.get("price_missing_count"),
                "pit_missing": result.get("pit_missing_count"),
                "fundamentals_missing": result.get("fundamentals_missing_count"),
                "pit_fundamentals_missing": result.get("pit_fundamentals_missing_count"),
            },
        )
        session.commit()
    return TradeCoverageAuditOut(**result)


@router.post("/actions/repair-alpha-names", response_model=AlphaNameRepairOut)
def repair_alpha_names(payload: AlphaNameRepairRequest):
    limit = payload.limit
    dry_run = bool(payload.dry_run)
    sample_size = max(int(payload.sample_size or 0), 0)
    allow_conflicts = bool(payload.allow_conflicts)

    total_candidates = 0
    renamed = 0
    skipped_same = 0
    skipped_conflict = 0
    errors: list[str] = []
    items: list[AlphaNameRepairItem] = []

    with get_session() as session:
        datasets = session.query(Dataset).order_by(Dataset.id.asc()).all()
        for dataset in datasets:
            if not _should_use_alpha_name(dataset, dataset.source_path):
                continue
            canonical_name = _canonical_alpha_dataset_name(dataset, dataset.source_path)
            if dataset.name == canonical_name:
                skipped_same += 1
                continue
            total_candidates += 1
            if limit and total_candidates > limit:
                break
            conflict = (
                session.query(Dataset)
                .filter(Dataset.name == canonical_name, Dataset.id != dataset.id)
                .first()
            )
            if conflict and not allow_conflicts:
                skipped_conflict += 1
                if len(items) < sample_size:
                    items.append(
                        AlphaNameRepairItem(
                            dataset_id=dataset.id,
                            old_name=dataset.name,
                            new_name=canonical_name,
                            status="conflict",
                            message=f"conflict_with={conflict.id}",
                        )
                    )
                continue
            if dry_run:
                if len(items) < sample_size:
                    items.append(
                        AlphaNameRepairItem(
                            dataset_id=dataset.id,
                            old_name=dataset.name,
                            new_name=canonical_name,
                            status="dry_run",
                            message=f"conflict_with={conflict.id}" if conflict else None,
                        )
                    )
                continue
            try:
                storage = _rename_dataset_storage_files(
                    _get_data_root(), dataset.id, dataset.name, canonical_name
                )
                old_name = dataset.name
                dataset.name = canonical_name
                dataset.updated_at = datetime.utcnow()
                session.commit()
                record_audit(
                    session,
                    action="dataset.rename",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    detail={
                        "old_name": old_name,
                        "new_name": canonical_name,
                        "storage": storage,
                    },
                )
                session.commit()
                renamed += 1
                if len(items) < sample_size:
                    items.append(
                        AlphaNameRepairItem(
                            dataset_id=dataset.id,
                            old_name=old_name,
                            new_name=canonical_name,
                            status="renamed",
                            moved_paths=storage.get("moved", []),
                            skipped_paths=storage.get("skipped", []),
                            message=f"conflict_with={conflict.id}" if conflict else None,
                        )
                    )
            except Exception as exc:
                errors.append(f"{dataset.id}:{exc}")
                if len(items) < sample_size:
                    items.append(
                        AlphaNameRepairItem(
                            dataset_id=dataset.id,
                            old_name=dataset.name,
                            new_name=canonical_name,
                            status="error",
                            message=str(exc),
                        )
                    )

    return AlphaNameRepairOut(
        total_candidates=total_candidates,
        renamed=renamed,
        skipped_same=skipped_same,
        skipped_conflict=skipped_conflict,
        errors=errors,
        items=items,
    )


@router.post("/actions/cleanup-alpha-duplicates", response_model=AlphaDuplicateCleanupOut)
def cleanup_alpha_duplicates(payload: AlphaDuplicateCleanupRequest):
    dry_run = bool(payload.dry_run)
    limit = payload.limit
    sample_size = max(int(payload.sample_size or 0), 0)

    total_groups = 0
    duplicate_groups = 0
    planned_delete = 0
    delete_ids: list[int] = []
    items: list[AlphaDuplicateCleanupItem] = []
    errors: list[str] = []

    with get_session() as session:
        datasets = session.query(Dataset).order_by(Dataset.id.asc()).all()
        groups: dict[str, list[Dataset]] = {}
        for dataset in datasets:
            if not _should_use_alpha_name(dataset, dataset.source_path):
                continue
            key = _canonical_alpha_dataset_name(dataset, dataset.source_path)
            groups.setdefault(key, []).append(dataset)

        total_groups = len(groups)
        for key, group in groups.items():
            if len(group) <= 1:
                continue
            duplicate_groups += 1
            if limit and duplicate_groups > limit:
                break
            best = None
            best_score = None
            summaries: dict[int, dict[str, Any]] = {}
            for dataset in group:
                summary = _dataset_series_summary(dataset)
                meta_start = _parse_date(dataset.coverage_start)
                meta_end = _parse_date(dataset.coverage_end)
                effective_start = summary.get("min_date") or meta_start
                effective_end = summary.get("max_date") or meta_end
                effective_days = summary.get("coverage_days") or (
                    (effective_end - effective_start).days
                    if effective_start and effective_end
                    else 0
                )
                summaries[dataset.id] = summary
                score = (
                    1 if summary.get("has_adjusted") else 0,
                    summary.get("rows") or 0,
                    effective_days,
                    (effective_end or date.min).toordinal(),
                    -(effective_start or date.max).toordinal(),
                    dataset.id,
                )
                if best_score is None or score > best_score:
                    best_score = score
                    best = dataset
            if not best:
                errors.append(f"{key}:no_candidate")
                continue
            drop_ids = [dataset.id for dataset in group if dataset.id != best.id]
            delete_ids.extend(drop_ids)
            planned_delete += len(drop_ids)
            if len(items) < sample_size:
                summary = summaries.get(best.id, {})
                items.append(
                    AlphaDuplicateCleanupItem(
                        key=key,
                        keep_id=best.id,
                        drop_ids=drop_ids,
                        keep_rows=int(summary.get("rows") or 0),
                        keep_start=summary.get("min_date").isoformat()
                        if summary.get("min_date")
                        else None,
                        keep_end=summary.get("max_date").isoformat()
                        if summary.get("max_date")
                        else None,
                        keep_has_adjusted=bool(summary.get("has_adjusted")),
                        message=f"candidates={len(group)}",
                    )
                )

    deleted_ids: list[int] = []
    if not dry_run and delete_ids:
        result = delete_datasets(DatasetDeleteRequest(dataset_ids=delete_ids))
        deleted_ids = result.deleted_ids

    return AlphaDuplicateCleanupOut(
        total_groups=total_groups,
        duplicate_groups=duplicate_groups,
        planned_delete=planned_delete,
        deleted_ids=deleted_ids,
        errors=errors,
        items=items,
    )


@router.get("/{dataset_id}/sync-jobs", response_model=list[DataSyncOut])
def list_dataset_sync_jobs(dataset_id: int):
    with get_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")
        return (
            session.query(DataSyncJob)
            .filter(DataSyncJob.dataset_id == dataset_id)
            .order_by(DataSyncJob.created_at.desc())
            .all()
        )


@router.post("/{dataset_id}/sync", response_model=DataSyncOut)
def create_sync_job(
    dataset_id: int, payload: DataSyncCreate, background_tasks: BackgroundTasks
):
    with get_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")

        source_path = payload.source_path or dataset.source_path
        if not source_path:
            raise HTTPException(status_code=400, detail="缺少数据路径")
        date_column = payload.date_column or "date"
        reset_history = bool(payload.reset_history)
        stored_source = _resolve_market_source(dataset, source_path)
        if _is_alpha_source(stored_source) and date_column.lower() == "date":
            date_column = "timestamp"
        if payload.stooq_only and _is_stooq_source(stored_source):
            if not _is_stooq_only_source(stored_source):
                stored_source = f"stooq-only:{_stooq_symbol(stored_source, dataset)}"

        existing = (
            session.query(DataSyncJob)
            .filter(
                DataSyncJob.dataset_id == dataset_id,
                DataSyncJob.source_path == stored_source,
                DataSyncJob.date_column == date_column,
                DataSyncJob.reset_history == reset_history,
                DataSyncJob.status.in_(ACTIVE_SYNC_STATUSES),
            )
            .order_by(DataSyncJob.created_at.desc())
            .first()
        )
        if existing:
            return existing

        job = DataSyncJob(
            dataset_id=dataset_id,
            source_path=stored_source,
            date_column=date_column,
            reset_history=reset_history,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        record_audit(
            session,
            action="data.sync.create",
            resource_type="data_sync_job",
            resource_id=job.id,
            detail={"dataset_id": dataset_id, "source_path": job.source_path},
        )
        session.commit()

    if payload.auto_run:
        _start_sync_queue_worker(0, _default_queue_min_delay())
    return job


@router.post("/sync-all", response_model=list[DataSyncOut])
def sync_all(background_tasks: BackgroundTasks, payload: DataSyncBatchRequest = DataSyncBatchRequest()):
    jobs: list[DataSyncOut] = []
    stooq_only = payload.stooq_only
    reset_history = bool(payload.reset_history)
    vendor_override = (payload.vendor or "").strip().lower()
    if vendor_override and vendor_override != "alpha":
        raise HTTPException(status_code=400, detail="当前仅支持 Alpha Vantage 数据源")
    with get_session() as session:
        datasets = session.query(Dataset).order_by(Dataset.updated_at.desc()).all()
        for dataset in datasets:
            if vendor_override and dataset.frequency and dataset.frequency.lower() != "daily":
                continue
            if not dataset.source_path and not vendor_override:
                continue
            source_path = dataset.source_path
            stored_source = source_path
            if vendor_override:
                symbol = _normalize_symbol_for_vendor(_dataset_symbol(dataset), dataset.region)
                if not symbol or symbol == "UNKNOWN":
                    continue
                if vendor_override == "alpha":
                    stored_source = f"alpha:{_alpha_symbol(symbol, dataset)}"
                elif vendor_override == "yahoo":
                    stored_source = f"yahoo:{_yahoo_symbol(symbol, dataset)}"
                else:
                    stored_source = f"stooq:{_stooq_symbol(f'stooq:{symbol}', dataset)}"
            else:
                if _is_stooq_source(source_path):
                    stored_source = f"stooq:{_stooq_symbol(source_path, dataset)}"
                elif _is_yahoo_source(source_path):
                    stored_source = f"yahoo:{_yahoo_source_symbol(source_path, dataset)}"
                elif _is_alpha_source(source_path):
                    stored_source = f"alpha:{_alpha_source_symbol(source_path, dataset)}"
                else:
                    path = _resolve_path(source_path)
                    data_root = _get_data_root()
                    if not str(path).startswith(str(data_root)) or not path.exists():
                        continue
                    stored_source = str(path)
            if stooq_only and _is_stooq_source(stored_source):
                if not _is_stooq_only_source(stored_source):
                    stored_source = f"stooq-only:{_stooq_symbol(stored_source, dataset)}"
            date_column = "timestamp" if _is_alpha_source(stored_source) else "date"
            active = (
                session.query(DataSyncJob)
                .filter(
                    DataSyncJob.dataset_id == dataset.id,
                    DataSyncJob.source_path == stored_source,
                    DataSyncJob.date_column == date_column,
                    DataSyncJob.reset_history == reset_history,
                    DataSyncJob.status.in_(ACTIVE_SYNC_STATUSES),
                )
                .first()
            )
            if active:
                continue
            job = DataSyncJob(
                dataset_id=dataset.id,
                source_path=stored_source,
                date_column=date_column,
                reset_history=reset_history,
            )
            session.add(job)
            session.flush()
            jobs.append(job)
            record_audit(
                session,
                action="data.sync.create",
                resource_type="data_sync_job",
                resource_id=job.id,
                detail={"dataset_id": dataset.id, "source_path": job.source_path},
            )
        session.commit()
    if payload.auto_run and jobs:
        _start_sync_queue_worker(0, _default_queue_min_delay())
    return jobs


@router.post("/sync-queue/run", response_model=DataSyncQueueRunOut)
def run_sync_queue(payload: DataSyncQueueRunRequest = DataSyncQueueRunRequest()):
    max_jobs = max(int(payload.max_jobs or 0), 0)
    min_delay_seconds = max(float(payload.min_delay_seconds or 0), 0.0)
    started = _start_sync_queue_worker(max_jobs, min_delay_seconds)
    with get_session() as session:
        pending = _count_pending_sync_jobs(session)
    return DataSyncQueueRunOut(
        started=started,
        running=SYNC_QUEUE_RUNNING,
        pending=pending,
        max_jobs=max_jobs,
        min_delay_seconds=min_delay_seconds,
    )


@router.post("/sync-jobs/clear", response_model=DataSyncQueueClearOut)
def clear_sync_queue(payload: DataSyncQueueClearRequest = DataSyncQueueClearRequest()):
    allowed_statuses = {"queued", "rate_limited"}
    statuses = [
        (status or "").strip().lower()
        for status in (payload.statuses or ["queued", "rate_limited"])
        if (status or "").strip().lower() in allowed_statuses
    ]
    if not statuses:
        raise HTTPException(status_code=400, detail="状态参数无效")
    with get_session() as session:
        query = session.query(DataSyncJob).filter(DataSyncJob.status.in_(statuses))
        if payload.only_alpha:
            query = query.filter(func.lower(DataSyncJob.source_path).like("alpha:%"))
        deleted = query.delete(synchronize_session=False)
        record_audit(
            session,
            action="data.sync.clear",
            resource_type="data_sync_job",
            resource_id=None,
            detail={"statuses": statuses, "only_alpha": payload.only_alpha, "deleted": deleted},
        )
        session.commit()
    return DataSyncQueueClearOut(
        deleted=deleted,
        statuses=statuses,
        only_alpha=payload.only_alpha,
    )


def _bulk_job_to_out(session, job: BulkSyncJob) -> BulkSyncOut:
    out = BulkSyncOut.model_validate(job, from_attributes=True)
    pending, running, completed = _bulk_job_counts(session, job)
    out.pending_sync_jobs = pending
    out.running_sync_jobs = running
    out.completed_sync_jobs = completed
    return out


def resume_bulk_sync_jobs() -> None:
    with SessionLocal() as session:
        jobs = (
            session.query(BulkSyncJob)
            .filter(BulkSyncJob.status.in_(("queued", "running")))
            .order_by(BulkSyncJob.created_at.asc())
            .all()
        )
    for job in jobs:
        _start_bulk_sync_worker(job.id)


@router.post("/actions/bulk-sync", response_model=BulkSyncOut)
def create_bulk_sync_job(payload: BulkSyncCreate):
    status_filter = (payload.status or "all").strip().lower()
    if status_filter not in {"all", "active", "delisted"}:
        raise HTTPException(status_code=400, detail="状态参数无效")
    batch_size = max(int(payload.batch_size or 0), 1)
    min_delay_seconds = max(float(payload.min_delay_seconds or 0), 0.0)
    refresh_listing_mode = (payload.refresh_listing_mode or "stale_only").strip().lower()
    if refresh_listing_mode not in {"always", "stale_only", "never"}:
        raise HTTPException(status_code=400, detail="刷新策略参数无效")
    refresh_listing_ttl_days = max(int(payload.refresh_listing_ttl_days or 0), 1)
    alpha_compact_days = max(int(payload.alpha_compact_days or 0), 1)
    project_only = bool(payload.project_only)
    params = {
        "status": status_filter,
        "batch_size": batch_size,
        "only_missing": bool(payload.only_missing),
        "auto_sync": bool(payload.auto_sync),
        "refresh_listing": bool(payload.refresh_listing),
        "refresh_listing_mode": refresh_listing_mode,
        "refresh_listing_ttl_days": refresh_listing_ttl_days,
        "alpha_incremental_enabled": bool(payload.alpha_incremental_enabled),
        "alpha_compact_days": alpha_compact_days,
        "min_delay_seconds": min_delay_seconds,
        "project_only": project_only,
    }
    with get_session() as session:
        project_symbols: list[str] | None = None
        project_benchmarks: list[str] | None = None
        if project_only:
            symbols, benchmarks = collect_active_project_symbols(session)
            project_symbols = symbols
            project_benchmarks = benchmarks
            if not project_symbols:
                raise HTTPException(status_code=400, detail="项目标的为空")
        active = (
            session.query(BulkSyncJob)
            .filter(BulkSyncJob.status.in_(("queued", "running", "paused")))
            .first()
        )
        if active:
            raise HTTPException(status_code=409, detail="已有全量任务正在运行")
        job = BulkSyncJob(
            status="queued",
            phase="listing_refresh",
            params=params,
            batch_size=batch_size,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        if project_only and project_symbols:
            log_dir = Path(settings.artifact_root) / f"bulk_sync_job_{job.id}"
            symbol_path = log_dir / "project_symbols.csv"
            write_symbol_list(symbol_path, project_symbols)
            params["symbol_whitelist_path"] = str(symbol_path)
            params["symbol_whitelist_count"] = len(project_symbols)
            params["symbol_whitelist_benchmarks"] = project_benchmarks or []
            job.params = params
            session.commit()
        out = _bulk_job_to_out(session, job)
    _start_bulk_sync_worker(job.id)
    return out


@router.get("/bulk-sync-jobs/latest", response_model=BulkSyncOut)
def get_latest_bulk_sync_job():
    with get_session() as session:
        job = session.query(BulkSyncJob).order_by(BulkSyncJob.created_at.desc()).first()
        if not job:
            raise HTTPException(status_code=404, detail="没有全量任务")
        return _bulk_job_to_out(session, job)


@router.get("/bulk-sync-jobs/page", response_model=BulkSyncPageOut)
def list_bulk_sync_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(BulkSyncJob).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size)
        total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
        if safe_page > total_pages:
            safe_page = total_pages
            offset = (safe_page - 1) * safe_page_size
        jobs = (
            session.query(BulkSyncJob)
            .order_by(BulkSyncJob.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        items = [_bulk_job_to_out(session, job) for job in jobs]
        return BulkSyncPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.post("/bulk-sync-jobs/{job_id}/pause", response_model=BulkSyncOut)
def pause_bulk_sync_job(job_id: int):
    with get_session() as session:
        job = session.get(BulkSyncJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="全量任务不存在")
        if job.status in {"success", "failed", "canceled"}:
            raise HTTPException(status_code=400, detail="任务已结束")
        if job.status == "paused":
            return _bulk_job_to_out(session, job)
        job.pause_requested = True
        if job.status == "queued":
            job.status = "paused"
            job.pause_requested = False
        job.updated_at = datetime.utcnow()
        session.commit()
        return _bulk_job_to_out(session, job)


@router.post("/bulk-sync-jobs/{job_id}/resume", response_model=BulkSyncOut)
def resume_bulk_sync_job(job_id: int):
    with get_session() as session:
        job = session.get(BulkSyncJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="全量任务不存在")
        if job.status in {"success", "failed", "canceled"}:
            raise HTTPException(status_code=400, detail="任务已结束")
        job.pause_requested = False
        job.status = "queued"
        job.updated_at = datetime.utcnow()
        session.commit()
        out = _bulk_job_to_out(session, job)
    _start_bulk_sync_worker(job_id)
    return out


@router.post("/bulk-sync-jobs/{job_id}/cancel", response_model=BulkSyncOut)
def cancel_bulk_sync_job(job_id: int):
    with get_session() as session:
        job = session.get(BulkSyncJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="全量任务不存在")
        if job.status in {"success", "failed", "canceled"}:
            return _bulk_job_to_out(session, job)
        job.cancel_requested = True
        if job.status in {"queued", "paused"}:
            job.status = "canceled"
            job.phase = "canceled"
            job.cancel_requested = False
            job.pause_requested = False
            job.ended_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        session.commit()
        return _bulk_job_to_out(session, job)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _count_business_days(start: date, end: date) -> int:
    day = start
    count = 0
    while day <= end:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


def _latest_complete_business_day() -> date:
    day = datetime.utcnow().date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _factor_cache_path(symbol: str) -> Path:
    return _get_data_root() / "factors" / f"{symbol.lower()}.csv"


def _resolve_factor_path(dataset: Dataset | None, symbol: str) -> Path:
    lean_root = _get_lean_root()
    lean_path = lean_root / "equity" / "usa" / "factor_files" / f"{symbol.lower()}.csv"
    cache_path = _factor_cache_path(symbol)
    if ALPHA_ONLY_PRICES:
        return cache_path
    if lean_path.exists():
        return lean_path
    if cache_path.exists():
        return cache_path
    return lean_path


def _write_factor_file(path: Path, factors: list[tuple[date, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for day, factor in factors:
            writer.writerow([day.strftime("%Y%m%d"), f"{factor:.8f}"])


def _build_factors_from_yahoo(symbol: str, dataset: Dataset | None) -> list[tuple[date, float]]:
    yahoo_symbol = _yahoo_symbol(symbol, dataset)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
        "?interval=1d&range=max"
    )
    try:
        global _yahoo_rate_limited_until
        if _yahoo_rate_limited_until and datetime.utcnow() < _yahoo_rate_limited_until:
            raise RuntimeError("YAHOO_RATE_LIMIT")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _yahoo_rate_limited_until = datetime.utcnow() + YAHOO_RATE_LIMIT_WINDOW
            return []
        return []
    except urllib.error.URLError:
        return []

    if not data:
        return []
    if b"Too Many Requests" in data:
        _yahoo_rate_limited_until = datetime.utcnow() + YAHOO_RATE_LIMIT_WINDOW
        return []

    payload = json.loads(data.decode("utf-8", errors="ignore"))
    chart = payload.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not result:
        return []
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [None])[0] or {}
    adjclose = (indicators.get("adjclose") or [None])[0] or {}
    closes = quote.get("close") or []
    adj_values = adjclose.get("adjclose") or []

    factors: list[tuple[date, float]] = []
    for idx, ts in enumerate(timestamps):
        if ts is None:
            continue
        close_val = closes[idx] if idx < len(closes) else None
        adj_val = adj_values[idx] if idx < len(adj_values) else None
        if close_val in (None, 0) or adj_val in (None, 0):
            continue
        factor = float(adj_val) / float(close_val)
        factors.append((datetime.utcfromtimestamp(ts).date(), factor))
    factors.sort(key=lambda item: item[0])
    return factors


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1]
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_datetime_bound(value: str | None, *, is_end: bool) -> datetime | None:
    if not value:
        return None
    parsed = _parse_datetime(value)
    if not parsed:
        return None
    if (" " not in value and "T" not in value) and is_end:
        return parsed + timedelta(days=1) - timedelta(seconds=1)
    return parsed


def _to_unix_seconds(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _get_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root).resolve()
    if settings.lean_data_folder:
        return Path(settings.lean_data_folder).resolve().parent
    raise HTTPException(status_code=500, detail="数据根目录未配置")


def _resolve_path(value: str) -> Path:
    data_root = _get_data_root()
    path = Path(value)
    if not path.is_absolute():
        path = data_root / path
    return path.resolve()


def _load_listing_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows.extend([dict(row) for row in reader])
    return rows


def _normalize_asset_types(values: list[str] | None) -> set[str]:
    if not values:
        return {"STOCK"}
    normalized = {item.strip().upper() for item in values if item and item.strip()}
    return normalized or {"STOCK"}


def _parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _extract_symbol_from_filename(path: Path) -> str:
    stem = path.stem
    parts = stem.split("_", 2)
    if len(parts) >= 3:
        symbol_part = parts[2]
    else:
        symbol_part = stem
    for suffix in ("_Daily", "_daily", "_D", "_d"):
        if symbol_part.endswith(suffix):
            symbol_part = symbol_part[: -len(suffix)]
            break
    return symbol_part.strip().upper()


def _load_available_symbols(adjusted_dir: Path, session: SessionLocal | None = None) -> set[str]:
    symbols: set[str] = set()
    if ALPHA_ONLY_PRICES and session is not None:
        datasets = session.query(Dataset).all()
        for dataset in datasets:
            vendor = (dataset.vendor or "").strip().lower()
            if vendor != "alpha":
                continue
            freq = (dataset.frequency or "").strip().lower()
            if freq and freq not in {"d", "day", "daily"}:
                continue
            adjusted_path = _series_path(dataset, adjusted=True)
            if not adjusted_path.exists():
                continue
            symbol = _dataset_symbol(dataset)
            if symbol:
                symbols.add(symbol.upper())
        return symbols

    for path in adjusted_dir.glob("*.csv"):
        if ALPHA_ONLY_PRICES:
            parts = path.stem.split("_", 2)
            vendor = parts[1] if len(parts) >= 3 else ""
            if vendor.upper() != "ALPHA":
                continue
        symbol = _extract_symbol_from_filename(path)
        if symbol:
            symbols.add(symbol)
    return symbols


def _load_symbol_alias_map(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not path.exists():
        return mapping
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            canonical = (row.get("canonical") or "").strip().upper()
            if not symbol or not canonical:
                continue
            mapping[symbol] = canonical
    return mapping


def _resolve_benchmark_path(
    adjusted_dir: Path, benchmark: str, vendor_preference: list[str]
) -> Path:
    candidates = list(adjusted_dir.glob(f"*_{benchmark}_*.csv"))
    if not candidates:
        candidates = list(adjusted_dir.glob(f"*_{benchmark}.csv"))
    if not candidates:
        raise RuntimeError(f"missing benchmark data for {benchmark}")

    def vendor_rank(path: Path) -> int:
        stem = path.stem
        parts = stem.split("_", 2)
        vendor = parts[1] if len(parts) > 1 else ""
        ranks = {v.upper(): i for i, v in enumerate(vendor_preference)}
        return ranks.get(vendor.upper(), len(ranks) + 1)

    return sorted(candidates, key=vendor_rank)[0]


def _load_trading_days(
    adjusted_dir: Path, benchmark: str, vendor_preference: list[str]
) -> list[date]:
    data_root = _get_data_root()
    days, _info = load_trading_days(data_root, adjusted_dir, benchmark, vendor_preference)
    if not days:
        raise RuntimeError("no trading days found in trading calendar")
    return days


def _pick_rebalance_dates(
    trading_days: list[date],
    start: date | None,
    end: date | None,
    weekday: int | None,
    mode: str,
) -> list[date]:
    dates: list[date] = []
    if mode == "week_open":
        last_week: tuple[int, int] | None = None
        for day in trading_days:
            if start and day < start:
                continue
            if end and day > end:
                break
            week_key = day.isocalendar()[:2]
            if week_key != last_week:
                dates.append(day)
                last_week = week_key
        return dates
    if weekday is None:
        raise RuntimeError("weekday required for rebalance-mode=weekday")
    for day in trading_days:
        if start and day < start:
            continue
        if end and day > end:
            break
        if day.weekday() == weekday:
            dates.append(day)
    return dates


def _load_pit_weekly_meta(pit_dir: Path) -> dict[str, str]:
    meta_path = pit_dir / "pit_weekly_calendar.json"
    if not meta_path.exists():
        return {"rebalance_mode": "week_open", "rebalance_day": "monday"}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"rebalance_mode": "week_open", "rebalance_day": "monday"}
    return {
        "rebalance_mode": str(payload.get("rebalance_mode") or "week_open"),
        "rebalance_day": str(payload.get("rebalance_day") or "monday"),
    }


def _parse_snapshot_date(path: Path, prefix: str) -> date | None:
    stem = path.stem
    if not stem.startswith(prefix):
        return None
    suffix = stem[len(prefix) :]
    if suffix.startswith("_"):
        suffix = suffix[1:]
    if not suffix:
        return None
    try:
        return datetime.strptime(suffix, "%Y%m%d").date()
    except ValueError:
        return None


def _load_snapshot_dates(pit_dir: Path, prefix: str) -> set[date]:
    dates: set[date] = set()
    for path in pit_dir.glob(f"{prefix}*.csv"):
        parsed = _parse_snapshot_date(path, prefix.rstrip("_"))
        if parsed:
            dates.add(parsed)
    return dates


def _load_pit_symbols(pit_dir: Path, dates: list[date]) -> set[str]:
    symbols: set[str] = set()
    for day in dates:
        path = pit_dir / f"pit_{day.strftime('%Y%m%d')}.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = (row.get("symbol") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
    return symbols


def _load_fundamentals_status(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            rows[symbol] = dict(row)
    return rows


def _has_fundamentals_cache(root: Path, symbol: str) -> bool:
    path = root / symbol
    if not path.exists() or not path.is_dir():
        return False
    return any(path.glob("*.json"))


def _audit_trade_coverage(
    asset_types: set[str],
    benchmark: str,
    vendor_preference: list[str],
    start: date | None,
    end: date | None,
    sample_size: int,
    pit_dir: Path,
    fundamentals_root: Path,
    pit_fundamentals_dir: Path,
) -> dict[str, object]:
    data_root = _get_data_root()
    listing_rows = _load_listing_rows(_resolve_listing_paths(None))
    symbol_meta: dict[str, str] = {}
    for row in listing_rows:
        symbol = _normalize_symbol(row.get("symbol", "")).upper()
        asset_type = (row.get("assetType") or "").strip().upper()
        if not symbol or symbol == "UNKNOWN":
            continue
        if asset_types and asset_type not in asset_types:
            continue
        symbol_meta[symbol] = asset_type or "STOCK"
    symbols = sorted(symbol_meta.keys())

    adjusted_dir = data_root / "curated_adjusted"
    if adjusted_dir.exists() and ALPHA_ONLY_PRICES:
        session = SessionLocal()
        try:
            available_symbols = _load_available_symbols(adjusted_dir, session)
        finally:
            session.close()
    else:
        available_symbols = _load_available_symbols(adjusted_dir) if adjusted_dir.exists() else set()
    symbol_map_path = data_root / "universe" / "symbol_map.csv"
    symbol_alias_map = _load_symbol_alias_map(symbol_map_path)
    missing_price: list[str] = []
    for symbol in symbols:
        if symbol in available_symbols:
            continue
        alias = symbol_alias_map.get(symbol)
        if alias and alias in available_symbols:
            continue
        missing_price.append(symbol)

    trading_days = _load_trading_days(adjusted_dir, benchmark, vendor_preference)
    pit_meta = _load_pit_weekly_meta(pit_dir)
    mode = pit_meta.get("rebalance_mode", "week_open").lower()
    day_name = pit_meta.get("rebalance_day", "monday").lower()
    weekday_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
    }
    weekday = weekday_map.get(day_name)
    rebalance_dates = _pick_rebalance_dates(trading_days, start, end, weekday, mode)
    index_map = {day: idx for idx, day in enumerate(trading_days)}
    expected_snapshot_dates: list[date] = []
    for rebalance_date in rebalance_dates:
        idx = index_map.get(rebalance_date)
        if idx is None or idx == 0:
            continue
        expected_snapshot_dates.append(trading_days[idx - 1])
    if start:
        expected_snapshot_dates = [d for d in expected_snapshot_dates if d >= start]
    if end:
        expected_snapshot_dates = [d for d in expected_snapshot_dates if d <= end]

    actual_snapshot_dates = sorted(_load_snapshot_dates(pit_dir, "pit_"))
    expected_set = set(expected_snapshot_dates)
    actual_set = set(actual_snapshot_dates)
    pit_missing_dates = sorted(expected_set - actual_set)
    pit_extra_dates = sorted(actual_set - expected_set)

    pit_symbol_dates = actual_snapshot_dates or expected_snapshot_dates
    pit_symbols = _load_pit_symbols(pit_dir, pit_symbol_dates)
    status_map = _load_fundamentals_status(fundamentals_root / "fundamentals_status.csv")
    missing_fundamentals: list[dict[str, str]] = []
    for symbol in sorted(pit_symbols):
        if _has_fundamentals_cache(fundamentals_root, symbol):
            continue
        status = status_map.get(symbol, {})
        missing_fundamentals.append(
            {
                "symbol": symbol,
                "status": status.get("status", "missing"),
                "updated_at": status.get("updated_at", ""),
                "message": status.get("message", "missing_cache"),
            }
        )

    pit_fund_dates = sorted(_load_snapshot_dates(pit_fundamentals_dir, "pit_fundamentals_"))
    pit_fund_set = set(pit_fund_dates)
    pit_fund_missing = sorted(actual_set - pit_fund_set)
    pit_fund_extra = sorted(pit_fund_set - actual_set)

    report_dir = Path(settings.artifact_root) / "data_audit" / datetime.utcnow().strftime(
        "trade_%Y%m%d_%H%M%S"
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    price_missing_path = report_dir / "price_missing_symbols.csv"
    pit_missing_path = report_dir / "pit_weekly_missing_dates.csv"
    pit_extra_path = report_dir / "pit_weekly_extra_dates.csv"
    fundamentals_missing_path = report_dir / "fundamentals_missing_symbols.csv"
    pit_fund_missing_path = report_dir / "pit_fundamentals_missing_dates.csv"
    pit_fund_extra_path = report_dir / "pit_fundamentals_extra_dates.csv"

    with price_missing_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "assetType", "alias"])
        for symbol in missing_price:
            writer.writerow([symbol, symbol_meta.get(symbol, ""), symbol_alias_map.get(symbol, "")])
    with pit_missing_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["snapshot_date"])
        for day in pit_missing_dates:
            writer.writerow([day.isoformat()])
    with pit_extra_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["snapshot_date"])
        for day in pit_extra_dates:
            writer.writerow([day.isoformat()])
    with fundamentals_missing_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "status", "updated_at", "message"])
        writer.writeheader()
        for row in missing_fundamentals:
            writer.writerow(row)
    with pit_fund_missing_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["snapshot_date"])
        for day in pit_fund_missing:
            writer.writerow([day.isoformat()])
    with pit_fund_extra_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["snapshot_date"])
        for day in pit_fund_extra:
            writer.writerow([day.isoformat()])

    sample_count = max(sample_size, 0)
    return {
        "report_dir": str(report_dir),
        "price_missing_count": len(missing_price),
        "price_missing_path": str(price_missing_path) if missing_price else None,
        "pit_expected_count": len(expected_set),
        "pit_existing_count": len(actual_set),
        "pit_missing_count": len(pit_missing_dates),
        "pit_missing_path": str(pit_missing_path) if pit_missing_dates else None,
        "pit_extra_count": len(pit_extra_dates),
        "pit_extra_path": str(pit_extra_path) if pit_extra_dates else None,
        "fundamentals_missing_count": len(missing_fundamentals),
        "fundamentals_missing_path": str(fundamentals_missing_path)
        if missing_fundamentals
        else None,
        "fundamentals_missing_sample": [
            row["symbol"] for row in missing_fundamentals[:sample_count]
        ],
        "pit_fundamentals_missing_count": len(pit_fund_missing),
        "pit_fundamentals_missing_path": str(pit_fund_missing_path)
        if pit_fund_missing
        else None,
        "pit_fundamentals_extra_count": len(pit_fund_extra),
        "pit_fundamentals_extra_path": str(pit_fund_extra_path)
        if pit_fund_extra
        else None,
    }


def _audit_alpha_coverage(
    session,
    asset_types: set[str],
    enqueue_missing: bool,
    enqueue_missing_adjusted: bool,
    sample_size: int,
) -> dict[str, object]:
    data_root = _get_data_root()
    rows = _load_listing_rows(_resolve_listing_paths(None))
    symbol_meta: dict[str, str] = {}
    for row in rows:
        symbol = _normalize_symbol(row.get("symbol", "")).upper()
        asset_type = (row.get("assetType") or "").strip().upper()
        if not symbol or symbol == "UNKNOWN":
            continue
        if asset_types and asset_type not in asset_types:
            continue
        symbol_meta[symbol] = asset_type or "STOCK"

    symbols = sorted(symbol_meta.keys())
    alpha_datasets = (
        session.query(Dataset)
        .filter(func.lower(Dataset.vendor) == "alpha")
        .all()
    )
    dataset_by_symbol: dict[str, Dataset] = {}
    for dataset in alpha_datasets:
        source = (dataset.source_path or "").strip()
        if _is_alpha_source(source):
            symbol = _alpha_source_symbol(source, dataset).upper()
        else:
            symbol = _alpha_symbol(_dataset_symbol(dataset), dataset).upper()
        dataset_by_symbol[symbol] = dataset

    missing_dataset = [sym for sym in symbols if sym not in dataset_by_symbol]
    missing_adjusted: list[str] = []
    for sym, dataset in dataset_by_symbol.items():
        if sym not in symbol_meta:
            continue
        adjusted_path = _series_path(dataset, adjusted=True)
        if not adjusted_path.exists():
            missing_adjusted.append(sym)

    enqueued = 0
    if enqueue_missing or enqueue_missing_adjusted:
        for sym in missing_dataset:
            if not enqueue_missing:
                break
            asset_type = symbol_meta.get(sym, "STOCK")
            asset_class = "ETF" if asset_type == "ETF" else "Equity"
            source_path = f"alpha:{sym.lower()}"
            dataset_name = f"Alpha_{sym}_Daily"
            dataset = (
                session.query(Dataset)
                .filter(
                    Dataset.source_path == source_path,
                    Dataset.vendor == "Alpha",
                    Dataset.frequency == "daily",
                )
                .first()
            )
            if not dataset:
                dataset = session.query(Dataset).filter(Dataset.name == dataset_name).first()
            if not dataset:
                dataset = Dataset(
                    name=dataset_name,
                    vendor="Alpha",
                    region="US",
                    frequency="daily",
                    asset_class=asset_class,
                    source_path=source_path,
                )
                session.add(dataset)
                session.flush()
                record_audit(
                    session,
                    action="dataset.create",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    detail={"name": dataset.name, "source": "audit"},
                )
            stored_source = _resolve_market_source(dataset, source_path)
            active = (
                session.query(DataSyncJob)
                .filter(
                    DataSyncJob.dataset_id == dataset.id,
                    DataSyncJob.source_path == stored_source,
                    DataSyncJob.date_column == "timestamp",
                    DataSyncJob.reset_history.is_(False),
                    DataSyncJob.status.in_(ACTIVE_SYNC_STATUSES),
                )
                .first()
            )
            if not active:
                job = DataSyncJob(
                    dataset_id=dataset.id,
                    source_path=stored_source,
                    date_column="timestamp",
                    reset_history=False,
                )
                session.add(job)
                session.flush()
                enqueued += 1
                record_audit(
                    session,
                    action="data.sync.create",
                    resource_type="data_sync_job",
                    resource_id=job.id,
                    detail={"dataset_id": dataset.id, "source_path": job.source_path},
                )

        if enqueue_missing_adjusted:
            for sym in missing_adjusted:
                dataset = dataset_by_symbol.get(sym)
                if not dataset:
                    continue
                stored_source = _resolve_market_source(dataset, dataset.source_path)
                active = (
                    session.query(DataSyncJob)
                    .filter(
                        DataSyncJob.dataset_id == dataset.id,
                        DataSyncJob.source_path == stored_source,
                        DataSyncJob.date_column == "timestamp",
                        DataSyncJob.reset_history.is_(False),
                        DataSyncJob.status.in_(ACTIVE_SYNC_STATUSES),
                    )
                    .first()
                )
                if active:
                    continue
                job = DataSyncJob(
                    dataset_id=dataset.id,
                    source_path=stored_source,
                    date_column="timestamp",
                    reset_history=False,
                )
                session.add(job)
                session.flush()
                enqueued += 1
                record_audit(
                    session,
                    action="data.sync.create",
                    resource_type="data_sync_job",
                    resource_id=job.id,
                    detail={"dataset_id": dataset.id, "source_path": job.source_path},
                )

    report_dir = Path(settings.artifact_root) / "data_audit" / datetime.utcnow().strftime(
        "alpha_%Y%m%d_%H%M%S"
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    missing_dataset_path = report_dir / "alpha_missing_datasets.csv"
    missing_adjusted_path = report_dir / "alpha_missing_adjusted.csv"
    with missing_dataset_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "assetType"])
        for sym in missing_dataset:
            writer.writerow([sym, symbol_meta.get(sym, "")])
    with missing_adjusted_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol"])
        for sym in missing_adjusted:
            writer.writerow([sym])

    sample_count = max(sample_size, 0)
    return {
        "total_symbols": len(symbols),
        "missing_dataset_count": len(missing_dataset),
        "missing_adjusted_count": len(missing_adjusted),
        "enqueued": enqueued,
        "report_dir": str(report_dir),
        "missing_dataset_path": str(missing_dataset_path) if missing_dataset else None,
        "missing_adjusted_path": str(missing_adjusted_path) if missing_adjusted else None,
        "sample_missing_dataset": missing_dataset[:sample_count],
        "sample_missing_adjusted": missing_adjusted[:sample_count],
    }


def _resolve_listing_paths(source_path: str | None) -> list[Path]:
    data_root = _get_data_root()
    if source_path:
        path = Path(source_path)
        if not path.is_absolute():
            path = data_root / path
        return [path.resolve()]

    preferred = data_root / "universe" / "alpha_symbol_life.csv"
    if preferred.exists():
        return [preferred]

    active = data_root / "universe" / "alpha_listing_status_active_latest.csv"
    delisted = data_root / "universe" / "alpha_listing_status_delisted_latest.csv"
    paths = [path for path in (active, delisted) if path.exists()]
    return paths or [preferred]


def _fetch_alpha_listing_status(state: str, date_value: str | None = None) -> bytes:
    global _alpha_rate_limited_until
    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        raise RuntimeError("ALPHA_KEY_MISSING")
    lock = _acquire_alpha_fetch_lock()
    if not lock:
        raise RuntimeError("ALPHA_LOCK_BUSY")
    try:
        _wait_alpha_rate_slot()
        params = {"function": "LISTING_STATUS", "apikey": api_key, "state": state}
        if date_value:
            params["date"] = date_value
        url = f"https://www.alphavantage.co/query?{urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "stocklean/1.0"})
        with urllib.request.urlopen(request, timeout=60) as handle:
            payload = handle.read()
        if payload[:1] == b"{":
            decoded = json.loads(payload.decode("utf-8", errors="ignore"))
            note = decoded.get("Note") or decoded.get("Information")
            if note:
                config = load_alpha_rate_config(_get_data_root())
                sleep_seconds = float(
                    config.get("rate_limit_sleep") or DEFAULT_RATE_LIMIT_SLEEP
                )
                _alpha_rate_limited_until = datetime.utcnow() + timedelta(seconds=sleep_seconds)
                _note_alpha_request(rate_limited=True)
                raise RuntimeError("ALPHA_RATE_LIMIT")
            _note_alpha_request()
            raise RuntimeError(f"alpha error: {decoded}")
        _note_alpha_request()
        return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            config = load_alpha_rate_config(_get_data_root())
            sleep_seconds = float(
                config.get("rate_limit_sleep") or DEFAULT_RATE_LIMIT_SLEEP
            )
            _alpha_rate_limited_until = datetime.utcnow() + timedelta(seconds=sleep_seconds)
            _note_alpha_request(rate_limited=True)
            raise RuntimeError("ALPHA_RATE_LIMIT") from exc
        _note_alpha_request()
        raise RuntimeError(f"Alpha Vantage 请求失败: {exc}") from exc
    except urllib.error.URLError as exc:
        _note_alpha_request()
        raise RuntimeError(f"Alpha Vantage 请求失败: {exc}") from exc
    except Exception:
        _note_alpha_request()
        raise
    finally:
        lock.release()


def _merge_symbol_life_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for row in rows:
        symbol = _normalize_symbol(row.get("symbol", "")).upper()
        if not symbol or symbol == "UNKNOWN":
            continue
        status = (row.get("status") or "").strip().lower()
        delisted = (row.get("delistingDate") or "").strip()
        existing = merged.get(symbol)
        if not existing:
            merged[symbol] = row
            continue
        existing_status = (existing.get("status") or "").strip().lower()
        existing_delisted = (existing.get("delistingDate") or "").strip()
        prefer = False
        if existing_status != "delisted" and status == "delisted":
            prefer = True
        elif not existing_delisted and delisted:
            prefer = True
        if prefer:
            merged[symbol] = row
    return [merged[key] for key in sorted(merged)]


def _write_symbol_life(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "symbol",
        "name",
        "exchange",
        "assetType",
        "ipoDate",
        "delistingDate",
        "status",
    ]
    tmp_path = output_path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})
    tmp_path.replace(output_path)


def _write_listing_bytes(payload: bytes, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp")
    tmp_path.write_bytes(payload)
    tmp_path.replace(output_path)


def _write_listing_versioned(
    data_root: Path,
    active_payload: bytes,
    delisted_payload: bytes,
    merged: list[dict[str, str]],
    snapshot_suffix: str,
) -> None:
    version_dir = data_root / "universe" / "listing_versions"
    active_path = version_dir / f"alpha_listing_status_active_{snapshot_suffix}.csv"
    delisted_path = version_dir / f"alpha_listing_status_delisted_{snapshot_suffix}.csv"
    symbol_life_path = version_dir / f"alpha_symbol_life_{snapshot_suffix}.csv"
    _write_listing_bytes(active_payload, active_path)
    _write_listing_bytes(delisted_payload, delisted_path)
    _write_symbol_life(merged, symbol_life_path)


def _refresh_alpha_listing() -> dict[str, int]:
    data_root = _get_data_root()
    active_payload = _fetch_alpha_listing_status("active")
    delisted_payload = _fetch_alpha_listing_status("delisted")
    active_path = data_root / "universe" / "alpha_listing_status_active_latest.csv"
    delisted_path = data_root / "universe" / "alpha_listing_status_delisted_latest.csv"
    _write_listing_bytes(active_payload, active_path)
    _write_listing_bytes(delisted_payload, delisted_path)
    rows = _load_listing_rows([active_path, delisted_path])
    merged = _merge_symbol_life_rows(rows)
    symbol_life_path = data_root / "universe" / "alpha_symbol_life.csv"
    _write_symbol_life(merged, symbol_life_path)
    snapshot_suffix = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    _write_listing_versioned(
        data_root,
        active_payload,
        delisted_payload,
        merged,
        snapshot_suffix,
    )
    return {
        "active": sum(1 for row in rows if (row.get("status") or "").strip().lower() == "active"),
        "delisted": sum(
            1 for row in rows if (row.get("status") or "").strip().lower() == "delisted"
        ),
        "total": len(merged),
    }


def _safe_delete_path(path: Path, allowed_roots: list[Path]) -> bool:
    if not path:
        return False
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return False
    for root in allowed_roots:
        try:
            root_resolved = root.resolve()
        except (OSError, RuntimeError):
            continue
        if str(resolved).startswith(str(root_resolved)):
            if resolved.is_dir():
                shutil.rmtree(resolved, ignore_errors=True)
            else:
                resolved.unlink(missing_ok=True)
            return True
    return False


def _is_stooq_source(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        lowered.startswith("stooq:")
        or lowered.startswith("stooq://")
        or lowered.startswith("stooq-only:")
        or lowered.startswith("stooq-only://")
    )


def _is_stooq_only_source(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("stooq-only:") or lowered.startswith("stooq-only://")


def _is_yahoo_source(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("yahoo:") or lowered.startswith("yahoo://")


def _is_alpha_source(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("alpha:") or lowered.startswith("alpha://")


def _normalize_symbol(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\.\-]", "", value.strip())
    return cleaned or "UNKNOWN"


def _stooq_symbol(source_path: str, dataset: Dataset | None) -> str:
    raw = source_path.strip()
    if raw.lower().startswith("stooq://"):
        raw = raw[8:]
    elif raw.lower().startswith("stooq:"):
        raw = raw[6:]
    elif raw.lower().startswith("stooq-only://"):
        raw = raw[13:]
    elif raw.lower().startswith("stooq-only:"):
        raw = raw[11:]
    symbol = _normalize_symbol(raw or (dataset.name if dataset else ""))
    symbol = symbol.lower()
    if "." not in symbol:
        region = (dataset.region or "").strip().lower() if dataset else ""
        suffix = "hk" if region in {"hk", "hongkong"} else "us"
        symbol = f"{symbol}.{suffix}"
    return symbol


def _yahoo_source_symbol(source_path: str, dataset: Dataset | None) -> str:
    raw = source_path.strip()
    if raw.lower().startswith("yahoo://"):
        raw = raw[8:]
    elif raw.lower().startswith("yahoo:"):
        raw = raw[6:]
    symbol = _normalize_symbol(raw or (_dataset_symbol(dataset) if dataset else ""))
    return _yahoo_symbol(symbol, dataset)


def _yahoo_symbol(symbol: str, dataset: Dataset | None) -> str:
    base = symbol.strip().upper()
    region = (dataset.region or "").strip().upper() if dataset else ""
    if region == "HK" and not base.endswith(".HK"):
        return f"{base}.HK"
    return base


def _alpha_source_symbol(source_path: str, dataset: Dataset | None) -> str:
    raw = source_path.strip()
    if raw.lower().startswith("alpha://"):
        raw = raw[8:]
    elif raw.lower().startswith("alpha:"):
        raw = raw[6:]
    symbol = _normalize_symbol(raw or (_dataset_symbol(dataset) if dataset else ""))
    return _alpha_symbol(symbol, dataset)


def _alpha_symbol(symbol: str, dataset: Dataset | None) -> str:
    base = symbol.strip().upper()
    region = (dataset.region or "").strip().upper() if dataset else ""
    if region == "HK" and not base.endswith(".HK"):
        return f"{base}.HK"
    return base


def _fetch_yahoo_csv(
    symbol: str,
    dataset_id: int,
    dataset_name: str,
    interval: str = "1d",
    range_value: str = "max",
) -> Path:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval={interval}&range={range_value}"
    )
    target_dir = _get_data_root() / "raw" / "yahoo"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{dataset_id}_{_safe_name(dataset_name)}.csv"
    target_path = target_dir / filename
    try:
        global _yahoo_rate_limited_until
        if _yahoo_rate_limited_until and datetime.utcnow() < _yahoo_rate_limited_until:
            raise RuntimeError("YAHOO_RATE_LIMIT")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _yahoo_rate_limited_until = datetime.utcnow() + YAHOO_RATE_LIMIT_WINDOW
            raise RuntimeError("YAHOO_RATE_LIMIT") from exc
        raise RuntimeError(f"Yahoo 请求失败: {exc}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Yahoo 请求失败: {exc}") from exc

    if not data:
        raise RuntimeError("Yahoo 返回空数据")
    if b"Too Many Requests" in data:
        _yahoo_rate_limited_until = datetime.utcnow() + YAHOO_RATE_LIMIT_WINDOW
        raise RuntimeError("YAHOO_RATE_LIMIT")

    payload = json.loads(data.decode("utf-8", errors="ignore"))
    chart = payload.get("chart") or {}
    error = chart.get("error")
    if error:
        raise RuntimeError("YAHOO_NOT_FOUND")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError("YAHOO_NOT_FOUND")
    timestamps = result.get("timestamp") or []
    indicators = (result.get("indicators") or {}).get("quote") or []
    if not timestamps or not indicators:
        raise RuntimeError("YAHOO_NOT_FOUND")
    quote = indicators[0] if indicators else {}

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    with target_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        for idx, ts in enumerate(timestamps):
            if ts is None:
                continue
            dt = datetime.utcfromtimestamp(ts).date().isoformat()
            writer.writerow(
                [
                    dt,
                    "" if idx >= len(opens) else _format_price(opens[idx]),
                    "" if idx >= len(highs) else _format_price(highs[idx]),
                    "" if idx >= len(lows) else _format_price(lows[idx]),
                    "" if idx >= len(closes) else _format_price(closes[idx]),
                    "" if idx >= len(volumes) else volumes[idx] or "",
                ]
            )
    return target_path


def _fetch_alpha_csv(
    symbol: str,
    dataset_id: int,
    dataset_name: str,
    outputsize: str = "full",
) -> Path:
    global _alpha_rate_limited_until
    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        raise RuntimeError("ALPHA_KEY_MISSING")
    lock = _acquire_alpha_fetch_lock()
    if not lock:
        raise RuntimeError("ALPHA_LOCK_BUSY")
    entitlement = (settings.alpha_vantage_entitlement or "").strip()
    url = (
        "https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol}"
        f"&outputsize={outputsize}&datatype=csv&apikey={api_key}"
    )
    if entitlement:
        url += f"&entitlement={entitlement}"
    target_dir = _get_data_root() / "raw" / "alpha"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{dataset_id}_{_safe_name(dataset_name)}.csv"
    target_path = target_dir / filename
    try:
        _wait_alpha_rate_slot()
        config = load_alpha_rate_config(_get_data_root())
        rate_limit_sleep = float(config.get("rate_limit_sleep") or DEFAULT_RATE_LIMIT_SLEEP)
        if _alpha_rate_limited_until and datetime.utcnow() < _alpha_rate_limited_until:
            raise RuntimeError("ALPHA_RATE_LIMIT")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _alpha_rate_limited_until = datetime.utcnow() + timedelta(seconds=rate_limit_sleep)
            _note_alpha_request(rate_limited=True)
            raise RuntimeError("ALPHA_RATE_LIMIT") from exc
        _note_alpha_request()
        raise RuntimeError(f"Alpha Vantage 请求失败: {exc}") from exc
    except urllib.error.URLError as exc:
        _note_alpha_request()
        raise RuntimeError(f"Alpha Vantage 请求失败: {exc}") from exc
    except Exception:
        _note_alpha_request()
        raise
    finally:
        lock.release()

    if not data:
        _note_alpha_request()
        raise RuntimeError("Alpha Vantage 返回空数据")
    if data.lstrip().startswith(b"{"):
        payload = json.loads(data.decode("utf-8", errors="ignore"))
        note = payload.get("Note") or payload.get("Information")
        error_msg = payload.get("Error Message") or payload.get("error")
        note_text = str(note or "").lower()
        error_text = str(error_msg or "").lower()
        premium_hint = any(
            keyword in note_text or keyword in error_text
            for keyword in ("premium endpoint", "premium only")
        )
        if premium_hint:
            _alpha_rate_limited_until = datetime.utcnow() + timedelta(seconds=rate_limit_sleep)
            _note_alpha_request(rate_limited=True)
            raise RuntimeError("ALPHA_RATE_LIMIT")
        if note:
            _alpha_rate_limited_until = datetime.utcnow() + timedelta(seconds=rate_limit_sleep)
            _note_alpha_request(rate_limited=True)
            raise RuntimeError("ALPHA_RATE_LIMIT")
        if error_msg:
            _note_alpha_request()
            raise RuntimeError("ALPHA_NOT_FOUND")
        _note_alpha_request()
        raise RuntimeError("Alpha Vantage 返回异常响应")

    header = data.splitlines()[0].decode("utf-8", errors="ignore").lower()
    if "timestamp" not in header:
        _note_alpha_request()
        raise RuntimeError("Alpha Vantage 返回缺少时间列")

    _note_alpha_request()
    tmp_path = target_path.with_suffix(".tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(target_path)
    return target_path


def _fetch_alpha_csv_with_retry(
    symbol: str,
    dataset_id: int,
    dataset_name: str,
    outputsize: str = "full",
) -> Path:
    last_error: Exception | None = None
    config = load_alpha_rate_config(_get_data_root())
    max_retries = int(config.get("max_retries") or 1)
    rate_limit_retries = int(config.get("rate_limit_retries") or 0)
    rate_limit_sleep = float(config.get("rate_limit_sleep") or DEFAULT_RATE_LIMIT_SLEEP)
    for attempt in range(1, max_retries + 1):
        try:
            return _fetch_alpha_csv(symbol, dataset_id, dataset_name, outputsize=outputsize)
        except RuntimeError as exc:
            last_error = exc
            code = str(exc)
            if code == "ALPHA_RATE_LIMIT":
                if attempt > rate_limit_retries:
                    raise
                time.sleep(rate_limit_sleep)
                continue
            if attempt >= max_retries:
                raise
            time.sleep(_compute_retry_delay(attempt))
    if last_error:
        raise last_error
    raise RuntimeError("Alpha Vantage 请求失败")


def _build_factors_from_alpha_csv(path: Path) -> list[tuple[date, float]]:
    factors: list[tuple[date, float]] = []
    if not path.exists():
        return factors
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return factors
        lower_map = {name.lower(): name for name in reader.fieldnames}
        date_key = lower_map.get("timestamp") or lower_map.get("date")
        adj_key = (
            lower_map.get("adjusted_close")
            or lower_map.get("adjusted close")
            or lower_map.get("adj_close")
            or lower_map.get("adj close")
        )
        close_key = lower_map.get("close")
        if not date_key or not adj_key or not close_key:
            return factors
        for row in reader:
            raw_date = (row.get(date_key) or "").strip()
            parsed = _parse_date(raw_date)
            if not parsed:
                continue
            adj_val = _parse_float(row.get(adj_key))
            close_val = _parse_float(row.get(close_key))
            if adj_val is None or close_val in (None, 0):
                continue
            factors.append((parsed, adj_val / close_val))
    factors.sort(key=lambda item: item[0])
    return factors


def _dataset_symbol(dataset: Dataset) -> str:
    source = (dataset.source_path or "").strip()
    if source and _is_stooq_source(source):
        raw = source
        if raw.lower().startswith("stooq://"):
            raw = raw[8:]
        elif raw.lower().startswith("stooq:"):
            raw = raw[6:]
        elif raw.lower().startswith("stooq-only://"):
            raw = raw[13:]
        elif raw.lower().startswith("stooq-only:"):
            raw = raw[11:]
        return _normalize_symbol(raw).upper()
    if source and _is_yahoo_source(source):
        raw = source
        if raw.lower().startswith("yahoo://"):
            raw = raw[8:]
        elif raw.lower().startswith("yahoo:"):
            raw = raw[6:]
        return _normalize_symbol(raw).upper()
    if source and _is_alpha_source(source):
        raw = source
        if raw.lower().startswith("alpha://"):
            raw = raw[8:]
        elif raw.lower().startswith("alpha:"):
            raw = raw[6:]
        return _normalize_symbol(raw).upper()
    if source:
        normalized = source.replace("\\", "/")
        last = normalized.split("/")[-1] or normalized
        return re.sub(r"\.(csv|zip)$", "", last, flags=re.IGNORECASE).upper()
    return (dataset.name or "").strip().upper()


def _normalize_symbol_for_vendor(symbol: str, region: str | None) -> str:
    cleaned = symbol.strip().upper()
    if region and region.strip().upper() == "HK":
        if cleaned.startswith("HK."):
            cleaned = cleaned[3:]
        if cleaned.endswith(".HK"):
            cleaned = cleaned[:-3]
    return cleaned


def _resolve_market_source(dataset: Dataset, source_path: str | None) -> str:
    if source_path and _is_stooq_source(source_path):
        raise HTTPException(status_code=400, detail="Stooq 数据源已禁用")
    if source_path and _is_yahoo_source(source_path):
        raise HTTPException(status_code=400, detail="Yahoo 数据源已禁用")
    if source_path and _is_alpha_source(source_path):
        return f"alpha:{_alpha_source_symbol(source_path, dataset)}"
    symbol = _normalize_symbol_for_vendor(_dataset_symbol(dataset), dataset.region)
    if not symbol or symbol == "UNKNOWN":
        raise HTTPException(status_code=400, detail="无法解析股票代码")
    vendor = (dataset.vendor or "").strip().lower()
    if vendor == "alpha":
        return f"alpha:{_alpha_symbol(symbol, dataset)}"
    if vendor in {"stooq", "yahoo"}:
        raise HTTPException(status_code=400, detail="非 Alpha 数据源已禁用")
    return f"alpha:{_alpha_symbol(symbol, dataset)}"


def _log_stooq_event(
    job_id: int | None,
    dataset_id: int,
    symbol: str,
    stage: str,
    message: str,
) -> None:
    data_root = _get_data_root()
    log_dir = data_root.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "stooq_fetch.log"
    timestamp = datetime.utcnow().isoformat()
    job_part = f"job={job_id}" if job_id is not None else "job=-"
    line = (
        f"{timestamp}\t{job_part}\tdataset={dataset_id}\t"
        f"symbol={symbol}\tstage={stage}\t{message}\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _fetch_stooq_csv(
    symbol: str,
    dataset_id: int,
    dataset_name: str,
    job_id: int | None = None,
) -> Path:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    target_dir = _get_data_root() / "raw" / "stooq"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{dataset_id}_{_safe_name(dataset_name)}.csv"
    target_path = target_dir / filename
    try:
        global _stooq_rate_limited_until
        if _stooq_rate_limited_until and datetime.utcnow() < _stooq_rate_limited_until:
            _log_stooq_event(job_id, dataset_id, symbol, "rate_limited", "window_active")
            raise RuntimeError("STOOQ_RATE_LIMIT")
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                _log_stooq_event(job_id, dataset_id, symbol, "http_error", str(response.status))
                raise RuntimeError(f"Stooq 请求失败: {response.status}")
            data = response.read()
    except urllib.error.URLError as exc:
        _log_stooq_event(job_id, dataset_id, symbol, "request_error", str(exc))
        raise RuntimeError(f"Stooq 请求失败: {exc}") from exc
    if not data or b"Date" not in data:
        if b"Exceeded the daily hits limit" in data:
            _stooq_rate_limited_until = datetime.utcnow() + STOOQ_RATE_LIMIT_WINDOW
            _log_stooq_event(job_id, dataset_id, symbol, "rate_limited", "daily_hits_limit")
            raise RuntimeError("STOOQ_RATE_LIMIT")
        if b"Not Found" in data or b"Unknown symbol" in data:
            _log_stooq_event(job_id, dataset_id, symbol, "not_found", "symbol")
            raise RuntimeError("STOOQ_NOT_FOUND")
        _log_stooq_event(job_id, dataset_id, symbol, "empty_response", "missing_date_header")
        raise RuntimeError("Stooq 返回空数据")
    target_path.write_bytes(data)
    _log_stooq_event(job_id, dataset_id, symbol, "downloaded", f"path={target_path}")
    return target_path


def _get_lean_root() -> Path:
    if settings.lean_data_folder:
        return Path(settings.lean_data_folder).resolve()
    return _get_data_root() / "lean"


def _ensure_support_directory(target_root: Path, source_root: Path, name: str) -> None:
    source = source_root / name
    target = target_root / name
    if not source.exists() or target.exists():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def _infer_market_code(dataset: Dataset | None) -> str:
    vendor = (dataset.vendor or "").lower() if dataset else ""
    if "nyse" in vendor:
        return "N"
    if "nasdaq" in vendor:
        return "Q"
    return "Q"


def _safe_name(value: str) -> str:
    cleaned = []
    for ch in value:
        if "a" <= ch <= "z" or "A" <= ch <= "Z" or "0" <= ch <= "9" or ch == "_":
            cleaned.append(ch)
        elif ch in {" ", "-", "."}:
            cleaned.append("_")
    name = "".join(cleaned).strip("_")
    name = re.sub(r"_+", "_", name)
    return name or "dataset"


def _frequency_label(value: str | None) -> str:
    if not value:
        return "Daily"
    normalized = value.strip().lower()
    if normalized in {"d", "day", "daily"}:
        return "Daily"
    if normalized in {"m", "min", "minute", "1min"}:
        return "Minute"
    return normalized.title()


def _should_use_alpha_name(dataset: Dataset | None, source_path: str | None = None) -> bool:
    if not dataset:
        return False
    if source_path and _is_alpha_source(source_path):
        return True
    vendor = (dataset.vendor or "").strip().lower()
    return vendor == "alpha"


def _canonical_alpha_dataset_name(dataset: Dataset, source_path: str | None = None) -> str:
    if source_path and _is_alpha_source(source_path):
        symbol = _alpha_source_symbol(source_path, dataset)
    else:
        symbol = _alpha_symbol(_dataset_symbol(dataset), dataset)
    return f"Alpha_{symbol}_{_frequency_label(dataset.frequency)}"


def _rename_dataset_storage_files(
    data_root: Path, dataset_id: int, old_name: str, new_name: str
) -> dict[str, list[str]]:
    moved: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    old_safe = _safe_name(old_name)
    new_safe = _safe_name(new_name)
    for folder in ("normalized", "curated", "curated_adjusted"):
        old_path = data_root / folder / f"{dataset_id}_{old_safe}.csv"
        new_path = data_root / folder / f"{dataset_id}_{new_safe}.csv"
        if old_path.exists():
            if new_path.exists():
                skipped.append(str(new_path))
                continue
            old_path.rename(new_path)
            moved.append(str(new_path))
        else:
            missing.append(str(old_path))
    old_versions = data_root / "curated_versions" / f"{dataset_id}_{old_safe}"
    new_versions = data_root / "curated_versions" / f"{dataset_id}_{new_safe}"
    if old_versions.exists():
        if new_versions.exists():
            skipped.append(str(new_versions))
        else:
            old_versions.rename(new_versions)
            moved.append(str(new_versions))
    else:
        missing.append(str(old_versions))
    return {"moved": moved, "skipped": skipped, "missing": missing}


def _scan_series_summary(path: Path) -> tuple[int, date | None, date | None]:
    if not path.exists():
        return 0, None, None
    rows = 0
    min_dt: date | None = None
    max_dt: date | None = None
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            for _ in reader:
                rows += 1
            return rows, None, None
        for row in reader:
            rows += 1
            parsed = _parse_datetime(row.get("date", ""))
            if not parsed:
                continue
            day = parsed.date()
            if min_dt is None or day < min_dt:
                min_dt = day
            if max_dt is None or day > max_dt:
                max_dt = day
    return rows, min_dt, max_dt


def _dataset_series_summary(dataset: Dataset) -> dict[str, Any]:
    adjusted_path = _series_path(dataset, adjusted=True)
    curated_path = _series_path(dataset, adjusted=False)
    has_adjusted = adjusted_path.exists()
    target_path = adjusted_path if has_adjusted else curated_path
    rows, min_dt, max_dt = _scan_series_summary(target_path) if target_path.exists() else (0, None, None)
    coverage_days = (max_dt - min_dt).days if min_dt and max_dt else 0
    return {
        "rows": rows,
        "min_date": min_dt,
        "max_date": max_dt,
        "coverage_days": coverage_days,
        "has_adjusted": has_adjusted,
    }


def _series_path(dataset: Dataset, adjusted: bool = False) -> Path:
    folder = "curated_adjusted" if adjusted else "curated"
    filename = f"{dataset.id}_{_safe_name(dataset.name)}.csv"
    return _get_data_root() / folder / filename


def _format_title(value: str) -> str:
    if not value:
        return ""
    return value[:1].upper() + value[1:].lower()


def _collect_csv_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.csv"))


_NORMALIZED_HEADER = ["date", "open", "high", "low", "close", "volume", "symbol"]


def _get_value(row: dict, row_lower: dict, keys: list[str]) -> str:
    for key in keys:
        column = row_lower.get(key)
        if column is None:
            continue
        value = row.get(column)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _format_datetime(dt: datetime) -> str:
    if dt.time().hour == 0 and dt.time().minute == 0 and dt.time().second == 0:
        return dt.date().isoformat()
    return dt.isoformat(sep=" ")


def _normalize_records(
    paths: list[Path],
    date_column: str,
    dataset_name: str,
    symbol_override: str | None = None,
) -> tuple[list[tuple[datetime, dict]], int, datetime | None, datetime | None, list[str]]:
    records: list[tuple[datetime, dict]] = []
    raw_rows = 0
    min_dt: datetime | None = None
    max_dt: datetime | None = None
    issues: list[str] = []
    date_key = date_column.lower()

    for path in paths:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                issues.append(f"CSV 缺少表头: {path}")
                continue
            row_lower = {name.lower(): name for name in reader.fieldnames}
            if date_key not in row_lower:
                issues.append(f"缺少日期列: {path}")
                continue

            for row in reader:
                raw_rows += 1
                date_raw = _get_value(row, row_lower, [date_key, "date", "datetime", "timestamp", "time"])
                parsed = _parse_datetime(date_raw)
                if not parsed:
                    continue
                if min_dt is None or parsed < min_dt:
                    min_dt = parsed
                if max_dt is None or parsed > max_dt:
                    max_dt = parsed

                symbol_value = symbol_override or _get_value(
                    row, row_lower, ["symbol", "ticker"]
                )
                record = {
                    "date": _format_datetime(parsed),
                    "open": _get_value(row, row_lower, ["open", "o"]),
                    "high": _get_value(row, row_lower, ["high", "h"]),
                    "low": _get_value(row, row_lower, ["low", "l"]),
                    "close": _get_value(row, row_lower, ["close", "adj_close", "adjclose", "c"]),
                    "volume": _get_value(row, row_lower, ["volume", "vol", "v"]),
                    "symbol": symbol_value or dataset_name,
                }
                records.append((parsed, record))

    records.sort(key=lambda item: item[0])
    return records, raw_rows, min_dt, max_dt, issues


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _get_last_date(path: Path) -> datetime | None:
    if not path.exists():
        return None
    last_dt: datetime | None = None
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            return None
        for row in reader:
            parsed = _parse_datetime(str(row.get("date", "")).strip())
            if parsed:
                last_dt = parsed
    return last_dt


def _append_normalized(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_NORMALIZED_HEADER)
        if write_header:
            writer.writeheader()
        for record in records:
            writer.writerow(record)


def _load_curated(path: Path) -> dict[datetime, dict]:
    curated: dict[datetime, dict] = {}
    if not path.exists():
        return curated
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            return curated
        for row in reader:
            parsed = _parse_datetime(str(row.get("date", "")).strip())
            if not parsed:
                continue
            curated[parsed] = row
    return curated


def _calc_min_interval(path: Path) -> tuple[int | None, int]:
    if not path.exists():
        return None, 0
    min_gap: int | None = None
    last_dt: datetime | None = None
    points = 0
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            return None, 0
        for row in reader:
            parsed = _parse_datetime(str(row.get("date", "")).strip())
            if not parsed:
                continue
            points += 1
            if last_dt is not None:
                gap = (parsed.date() - last_dt.date()).days
                if gap > 0:
                    if min_gap is None or gap < min_gap:
                        min_gap = gap
            last_dt = parsed
    return min_gap, points


def _load_candles(
    path: Path,
    start_dt: datetime | None,
    end_dt: datetime | None,
) -> list[dict]:
    candles: list[dict] = []
    if not path.exists():
        return candles
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            return candles
        for row in reader:
            parsed = _parse_datetime(str(row.get("date", "")).strip())
            if not parsed:
                continue
            if start_dt and parsed < start_dt:
                continue
            if end_dt and parsed > end_dt:
                continue
            open_val = _parse_float(row.get("open"))
            high_val = _parse_float(row.get("high"))
            low_val = _parse_float(row.get("low"))
            close_val = _parse_float(row.get("close"))
            if open_val is None or high_val is None or low_val is None or close_val is None:
                continue
            candles.append(
                {
                    "time": _to_unix_seconds(parsed),
                    "open": open_val,
                    "high": high_val,
                    "low": low_val,
                    "close": close_val,
                    "volume": _parse_float(row.get("volume")),
                }
            )
    return candles


def _load_adjusted_line(
    path: Path,
    start_dt: datetime | None,
    end_dt: datetime | None,
) -> list[dict]:
    points: list[dict] = []
    if not path.exists():
        return points
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            return points
        for row in reader:
            parsed = _parse_datetime(str(row.get("date", "")).strip())
            if not parsed:
                continue
            if start_dt and parsed < start_dt:
                continue
            if end_dt and parsed > end_dt:
                continue
            close_val = _parse_float(row.get("close"))
            if close_val is None:
                continue
            points.append({"time": _to_unix_seconds(parsed), "value": close_val})
    return points


def _row_score(row: dict) -> int:
    return sum(1 for key in _NORMALIZED_HEADER if str(row.get(key, "")).strip())


def _write_curated(path: Path, records: dict[datetime, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_NORMALIZED_HEADER)
        writer.writeheader()
        for timestamp in sorted(records.keys()):
            row = records[timestamp]
            writer.writerow({key: row.get(key, "") for key in _NORMALIZED_HEADER})


def _write_snapshot(
    dataset_id: int, dataset_name: str, records: dict[datetime, dict]
) -> Path | None:
    if not records:
        return None
    version_dir = _get_data_root() / "curated_versions" / f"{dataset_id}_{_safe_name(dataset_name)}"
    version_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    snapshot_path = version_dir / f"{stamp}.csv"
    _write_curated(snapshot_path, records)
    return snapshot_path


def _resolve_symbol_name(dataset_name: str, records: dict[datetime, dict]) -> str:
    for row in records.values():
        symbol = str(row.get("symbol", "")).strip()
        if symbol:
            return symbol
    return dataset_name


def _load_map_file(path: Path) -> list[tuple[date, str, str]]:
    entries: list[tuple[date, str, str]] = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 3:
                continue
            raw_date = row[0].strip()
            symbol = row[1].strip()
            market = row[2].strip()
            if not raw_date or not symbol:
                continue
            try:
                parsed = datetime.strptime(raw_date, "%Y%m%d").date()
            except ValueError:
                continue
            entries.append((parsed, symbol, market))
    entries.sort(key=lambda item: item[0])
    return entries


def _find_map_file(symbol: str, lean_root: Path) -> tuple[Path | None, list[tuple[date, str, str]]]:
    map_dir = lean_root / "equity" / "usa" / "map_files"
    if not map_dir.exists():
        return None, []
    target = map_dir / f"{symbol.lower()}.csv"
    if target.exists():
        return target, _load_map_file(target)
    for candidate in map_dir.glob("*.csv"):
        entries = _load_map_file(candidate)
        if any(sym.lower() == symbol.lower() for _, sym, _ in entries):
            return candidate, entries
    return None, []


def _resolve_canonical_symbol(symbol: str, lean_root: Path) -> tuple[str, Path | None, str | None]:
    map_path, entries = _find_map_file(symbol, lean_root)
    if not entries:
        return symbol.upper(), map_path, None
    last_symbol = entries[-1][1].strip()
    market_code = entries[-1][2].strip() if len(entries[-1]) > 2 else None
    return (last_symbol or symbol).upper(), map_path, market_code


def _load_factor_file(path: Path) -> list[tuple[date, float]]:
    factors: list[tuple[date, float]] = []
    if not path.exists():
        return factors
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            raw_date = row[0].strip()
            raw_factor = row[3].strip() if len(row) >= 4 else row[1].strip()
            if not raw_date or not raw_factor:
                continue
            try:
                parsed = datetime.strptime(raw_date, "%Y%m%d").date()
                factor = float(raw_factor)
            except ValueError:
                continue
            factors.append((parsed, factor))
    factors.sort(key=lambda item: item[0])
    return factors


def _merge_factor_history(
    base: list[tuple[date, float]],
    updates: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    if not base:
        return updates
    if not updates:
        return base
    merged = {day: factor for day, factor in base}
    for day, factor in updates:
        merged[day] = factor
    return sorted(merged.items(), key=lambda item: item[0])


def _apply_price_factors(
    records: dict[datetime, dict], factors: list[tuple[date, float]]
) -> dict[datetime, dict]:
    if not records or not factors:
        return {}
    adjusted: dict[datetime, dict] = {}
    sorted_items = sorted(records.items(), key=lambda item: item[0])
    factor_index = 0
    current_factor = factors[0][1]
    for timestamp, row in sorted_items:
        while factor_index + 1 < len(factors) and factors[factor_index + 1][0] <= timestamp.date():
            factor_index += 1
            current_factor = factors[factor_index][1]
        try:
            open_val = float(row.get("open", "")) if row.get("open") not in ("", None) else None
            high_val = float(row.get("high", "")) if row.get("high") not in ("", None) else None
            low_val = float(row.get("low", "")) if row.get("low") not in ("", None) else None
            close_val = float(row.get("close", "")) if row.get("close") not in ("", None) else None
        except ValueError:
            continue
        if current_factor and current_factor > 0:
            open_val = open_val * current_factor if open_val is not None else None
            high_val = high_val * current_factor if high_val is not None else None
            low_val = low_val * current_factor if low_val is not None else None
            close_val = close_val * current_factor if close_val is not None else None
        adjusted[timestamp] = {
            "date": row.get("date", ""),
            "open": _format_price(open_val),
            "high": _format_price(high_val),
            "low": _format_price(low_val),
            "close": _format_price(close_val),
            "volume": row.get("volume", ""),
            "symbol": row.get("symbol", ""),
        }
    return adjusted


def _sanitize_cliffs(
    records: dict[datetime, dict], threshold: float = 0.6
) -> tuple[dict[datetime, dict], int]:
    if not records:
        return {}, 0
    sanitized: dict[datetime, dict] = {}
    count = 0
    prev_close: float | None = None
    scale = 1.0
    for timestamp, row in sorted(records.items(), key=lambda item: item[0]):
        close_raw = _parse_float(row.get("close"))
        if close_raw is None:
            sanitized[timestamp] = row
            continue
        scaled_close = close_raw * scale
        if prev_close is not None and prev_close > 0:
            pct = (scaled_close - prev_close) / prev_close
            if abs(pct) >= threshold and scaled_close != 0:
                scale *= prev_close / scaled_close
                count += 1
                scaled_close = close_raw * scale
        open_raw = _parse_float(row.get("open"))
        high_raw = _parse_float(row.get("high"))
        low_raw = _parse_float(row.get("low"))
        sanitized[timestamp] = {
            **row,
            "open": _format_price(open_raw * scale if open_raw is not None else None),
            "high": _format_price(high_raw * scale if high_raw is not None else None),
            "low": _format_price(low_raw * scale if low_raw is not None else None),
            "close": _format_price(scaled_close),
        }
        prev_close = scaled_close
    return sanitized, count


def _should_export_lean(dataset: Dataset | None) -> bool:
    if not dataset:
        return False
    asset = (dataset.asset_class or "").strip().lower()
    if asset and asset not in {"equity", "stock", "etf"}:
        return False
    region = (dataset.region or "").strip().lower()
    if region and region not in {"us", "usa", "unitedstates", "united states"}:
        return False
    freq = (dataset.frequency or "").strip().lower()
    if freq and freq not in {"d", "day", "daily"}:
        return False
    return True


def _to_scaled_int(value: str) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(round(float(text) * 10000))
    except ValueError:
        return None


def _export_lean_daily_to_root(
    dataset: Dataset | None,
    records: dict[datetime, dict],
    dataset_name: str,
    lean_root: Path,
) -> Path | None:
    if not records or not _should_export_lean(dataset):
        return None
    symbol = _normalize_symbol(_resolve_symbol_name(dataset_name, records)).lower()
    if not symbol or symbol == "unknown":
        return None
    equity_root = lean_root / "equity" / "usa"
    daily_dir = equity_root / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for timestamp in sorted(records.keys()):
        row = records[timestamp]
        open_val = _to_scaled_int(row.get("open"))
        high_val = _to_scaled_int(row.get("high"))
        low_val = _to_scaled_int(row.get("low"))
        close_val = _to_scaled_int(row.get("close"))
        if None in {open_val, high_val, low_val, close_val}:
            continue
        volume_raw = str(row.get("volume", "")).strip()
        try:
            volume_val = int(float(volume_raw)) if volume_raw else 0
        except ValueError:
            volume_val = 0
        line = f"{timestamp.strftime('%Y%m%d')} 00:00,{open_val},{high_val},{low_val},{close_val},{volume_val}"
        lines.append(line)

    if not lines:
        return None

    tmp_csv = daily_dir / f"{symbol}.csv"
    with tmp_csv.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")

    zip_path = daily_dir / f"{symbol}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp_csv, arcname=f"{symbol}.csv")
    tmp_csv.unlink(missing_ok=True)

    market_code = _infer_market_code(dataset)
    map_dir = equity_root / "map_files"
    map_dir.mkdir(parents=True, exist_ok=True)
    map_path = map_dir / f"{symbol}.csv"
    if not map_path.exists():
        start_date = min(records.keys()).strftime("%Y%m%d")
        end_date = "20501231"
        with map_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(f"{start_date},{symbol},{market_code}\n{end_date},{symbol},{market_code}\n")

    factor_dir = equity_root / "factor_files"
    factor_dir.mkdir(parents=True, exist_ok=True)
    factor_path = factor_dir / f"{symbol}.csv"
    if not factor_path.exists():
        start_date = min(records.keys()).strftime("%Y%m%d")
        with factor_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(f"{start_date},1,1,1\n")

    return zip_path


def _export_lean_daily(
    dataset: Dataset | None,
    records: dict[datetime, dict],
    dataset_name: str,
) -> Path | None:
    return _export_lean_daily_to_root(dataset, records, dataset_name, _get_lean_root())


def _scan_csv_file(path: Path, date_column: str) -> tuple[int, datetime | None, datetime | None]:
    rows = 0
    min_dt: datetime | None = None
    max_dt: datetime | None = None
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or date_column not in reader.fieldnames:
            raise ValueError(f"缺少日期列: {path}")
        for row in reader:
            rows += 1
            parsed = _parse_datetime(row.get(date_column, "").strip())
            if not parsed:
                continue
            if min_dt is None or parsed < min_dt:
                min_dt = parsed
            if max_dt is None or parsed > max_dt:
                max_dt = parsed
    return rows, min_dt, max_dt


def _scan_path(path: Path, date_column: str) -> tuple[int, datetime | None, datetime | None, list[str]]:
    issues: list[str] = []
    if path.is_file():
        try:
            rows, min_dt, max_dt = _scan_csv_file(path, date_column)
            return rows, min_dt, max_dt, issues
        except ValueError as exc:
            issues.append(str(exc))
            return 0, None, None, issues

    csv_files = list(path.rglob("*.csv")) if path.is_dir() else []
    if not csv_files:
        issues.append("未找到 CSV 文件")
        return 0, None, None, issues

    total_rows = 0
    min_dt: datetime | None = None
    max_dt: datetime | None = None
    for file_path in csv_files:
        try:
            rows, file_min, file_max = _scan_csv_file(file_path, date_column)
            total_rows += rows
            if file_min and (min_dt is None or file_min < min_dt):
                min_dt = file_min
            if file_max and (max_dt is None or file_max > max_dt):
                max_dt = file_max
        except ValueError as exc:
            issues.append(str(exc))
            continue

    return total_rows, min_dt, max_dt, issues


def run_data_sync(job_id: int, spawn_retry_thread: bool = True) -> None:
    session = SessionLocal()
    try:
        job = session.get(DataSyncJob, job_id)
        if not job:
            return
        if job.next_retry_at and datetime.utcnow() < job.next_retry_at:
            return
        job.next_retry_at = None
        job.status = "running"
        job.started_at = datetime.utcnow()
        _set_job_stage(session, job, "fetch", 0.2)

        dataset = session.get(Dataset, job.dataset_id)
        source_path = job.source_path
        source_label = source_path
        issues: list[str] = []
        dataset_name = dataset.name if dataset else f"dataset_{job.dataset_id}"
        if dataset and _should_use_alpha_name(dataset, source_path):
            canonical_name = _canonical_alpha_dataset_name(dataset, source_path)
            if dataset_name != canonical_name:
                try:
                    rename_report = _rename_dataset_storage_files(
                        _get_data_root(), dataset.id, dataset_name, canonical_name
                    )
                    dataset.name = canonical_name
                    dataset.updated_at = datetime.utcnow()
                    session.commit()
                    record_audit(
                        session,
                        action="dataset.rename",
                        resource_type="dataset",
                        resource_id=dataset.id,
                        detail={
                            "old_name": dataset_name,
                            "new_name": canonical_name,
                            "source": source_path,
                            "storage": rename_report,
                        },
                    )
                    session.commit()
                    dataset_name = canonical_name
                except Exception as exc:
                    issues.append(f"rename_failed:{exc}")

        output_name = f"{job.dataset_id}_{_safe_name(dataset_name)}.csv"
        normalized_path = _get_data_root() / "normalized" / output_name
        curated_path = _get_data_root() / "curated" / output_name
        adjusted_path = _get_data_root() / "curated_adjusted" / output_name
        symbol_override: str | None = None
        reset_history = bool(job.reset_history)
        factor_source: str | None = None
        alpha_meta: dict[str, Any] | None = None
        alpha_coverage_end: date | None = None
        alpha_latest_complete: date | None = None
        alpha_outputsize: str | None = None
        alpha_compact_fallback = False
        alpha_symbol: str | None = None
        stooq_only = _is_stooq_only_source(source_path)
        stooq_symbol: str | None = None
        stooq_logged_start = False
        if dataset and _is_stooq_source(source_path):
            stooq_symbol = _stooq_symbol(source_path, dataset)
            _log_stooq_event(job.id, job.dataset_id, stooq_symbol, "start", "sync")
            stooq_logged_start = True
            coverage_end = _parse_date(dataset.coverage_end)
            latest_complete = _latest_complete_business_day()
            if not reset_history and coverage_end and coverage_end >= latest_complete:
                curated_records = _load_curated(curated_path) if curated_path.exists() else {}
                needs_adjusted = bool(curated_records) and not adjusted_path.exists()
                cliff_count = 0
                if needs_adjusted:
                    symbol_hint = _dataset_symbol(dataset) or dataset_name
                    lean_root = _get_lean_root()
                    canonical_symbol, map_path, _ = _resolve_canonical_symbol(
                        symbol_hint, lean_root
                    )
                    symbol_override = canonical_symbol
                    if ALPHA_ONLY_PRICES:
                        factors = []
                        factor_source = "alpha_only_skip"
                    else:
                        factor_path = _resolve_factor_path(dataset, canonical_symbol)
                        factors = _load_factor_file(factor_path)
                        if factors:
                            factor_source = "lean"
                        else:
                            factors = _build_factors_from_yahoo(canonical_symbol, dataset)
                            if factors:
                                factor_source = "yahoo"
                                _write_factor_file(_factor_cache_path(canonical_symbol), factors)
                    adjusted_records = _apply_price_factors(curated_records, factors)
                    adjusted_records, cliff_count = _sanitize_cliffs(adjusted_records)
                    if adjusted_records:
                        _write_curated(adjusted_path, adjusted_records)
                        lean_adjusted_root = _get_data_root() / "lean_adjusted"
                        base_lean_root = _get_lean_root()
                        _ensure_support_directory(
                            lean_adjusted_root, base_lean_root, "symbol-properties"
                        )
                        _ensure_support_directory(
                            lean_adjusted_root, base_lean_root, "market-hours"
                        )
                        _export_lean_daily_to_root(
                            dataset, adjusted_records, dataset_name, lean_adjusted_root
                        )
                job.status = "success"
                message_parts = [
                    "no_update",
                    f"coverage_end={dataset.coverage_end}",
                    f"latest_complete={latest_complete.isoformat()}",
                ]
                if needs_adjusted:
                    message_parts.append("backfill_adjusted")
                if factor_source in {"alpha", "alpha_cache"}:
                    message_parts.append("factor=alpha")
                elif factor_source == "yahoo":
                    message_parts.append("factor=yahoo")
                elif factor_source == "lean":
                    message_parts.append("factor=lean")
                else:
                    message_parts.append("factor=missing")
                if cliff_count:
                    message_parts.append(f"cliff_sanitized={cliff_count}")
                _log_stooq_event(
                    job.id,
                    job.dataset_id,
                    stooq_symbol,
                    "skip_no_update",
                    f"coverage_end={dataset.coverage_end};latest_complete={latest_complete.isoformat()}",
                )
                job.message = "; ".join(message_parts)
                job.ended_at = datetime.utcnow()
                job.normalized_path = str(normalized_path) if normalized_path.exists() else None
                job.output_path = str(curated_path) if curated_path.exists() else None
                job.adjusted_path = str(adjusted_path) if adjusted_path.exists() else None
                record_audit(
                    session,
                    action="data.sync.skip",
                    resource_type="data_sync_job",
                    resource_id=job.id,
                    detail={
                        "dataset_id": job.dataset_id,
                        "coverage_end": dataset.coverage_end,
                        "latest_complete": latest_complete.isoformat(),
                        "backfill_adjusted": needs_adjusted,
                        "factor_source": factor_source or "missing",
                    },
                )
                session.commit()
                return
        if _is_stooq_source(source_path):
            stooq_symbol = stooq_symbol or _stooq_symbol(source_path, dataset)
            if not stooq_logged_start:
                _log_stooq_event(job.id, job.dataset_id, stooq_symbol, "start", "sync")
            used_fallback = False
            try:
                path = _fetch_stooq_csv(stooq_symbol, job.dataset_id, dataset_name, job.id)
            except RuntimeError as exc:
                code = str(exc)
                if code in {"STOOQ_RATE_LIMIT", "STOOQ_NOT_FOUND"}:
                    if stooq_only:
                        if code == "STOOQ_RATE_LIMIT":
                            _schedule_retry(
                                session,
                                job,
                                reason="stooq_only; reason=STOOQ_RATE_LIMIT",
                                min_delay=int(STOOQ_RATE_LIMIT_WINDOW.total_seconds()),
                                status="rate_limited",
                                spawn_thread=spawn_retry_thread,
                            )
                            _log_stooq_event(
                                job.id,
                                job.dataset_id,
                                stooq_symbol,
                                "blocked",
                                "stooq_only; STOOQ_RATE_LIMIT",
                            )
                            return
                        job.status = "not_found"
                        job.message = "stooq_only; reason=STOOQ_NOT_FOUND"
                        job.ended_at = datetime.utcnow()
                        _log_stooq_event(
                            job.id,
                            job.dataset_id,
                            stooq_symbol,
                            "blocked",
                            "stooq_only; STOOQ_NOT_FOUND",
                        )
                        record_audit(
                            session,
                            action="data.sync.blocked",
                            resource_type="data_sync_job",
                            resource_id=job.id,
                            detail={"dataset_id": job.dataset_id, "reason": job.message},
                        )
                        session.commit()
                        return
                    _log_stooq_event(job.id, job.dataset_id, stooq_symbol, "fallback_yahoo", code)
                    base_symbol = (
                        stooq_symbol.split(".", 1)[0]
                        if "." in stooq_symbol
                        else stooq_symbol
                    )
                    yahoo_symbol = _yahoo_symbol(base_symbol, dataset)
                    try:
                        path = _fetch_yahoo_csv(yahoo_symbol, job.dataset_id, dataset_name)
                        source_label = f"yahoo:{yahoo_symbol}"
                        symbol_override = base_symbol.upper()
                        used_fallback = True
                        issues.append(
                            "fallback=yahoo"
                            if code == "STOOQ_RATE_LIMIT"
                            else "fallback=yahoo(stooq_not_found)"
                        )
                        _log_stooq_event(
                            job.id,
                            job.dataset_id,
                            stooq_symbol,
                            "fallback_success",
                            f"source=yahoo:{yahoo_symbol}",
                        )
                    except RuntimeError as yahoo_exc:
                        _log_stooq_event(
                            job.id,
                            job.dataset_id,
                            stooq_symbol,
                            "fallback_failed",
                            str(yahoo_exc),
                        )
                        yahoo_code = str(yahoo_exc)
                        if yahoo_code == "YAHOO_RATE_LIMIT":
                            _schedule_retry(
                                session,
                                job,
                                reason="stooq+yahoo; rate_limited",
                                min_delay=int(
                                    max(STOOQ_RATE_LIMIT_WINDOW, YAHOO_RATE_LIMIT_WINDOW).total_seconds()
                                ),
                                status="rate_limited",
                                spawn_thread=spawn_retry_thread,
                            )
                            return
                        elif yahoo_code == "YAHOO_NOT_FOUND":
                            job.status = "not_found"
                            job.message = "Stooq 与 Yahoo 均未覆盖该代码"
                        else:
                            _schedule_retry(
                                session,
                                job,
                                reason=f"yahoo_fallback_failed: {yahoo_code}",
                                spawn_thread=spawn_retry_thread,
                            )
                            return
                        job.ended_at = datetime.utcnow()
                        record_audit(
                            session,
                            action="data.sync.blocked",
                            resource_type="data_sync_job",
                            resource_id=job.id,
                            detail={"dataset_id": job.dataset_id, "reason": job.message},
                        )
                        session.commit()
                        return
                else:
                    if code.startswith("Stooq 请求失败") or code == "Stooq 返回空数据":
                        _schedule_retry(
                            session,
                            job,
                            reason=code,
                            spawn_thread=spawn_retry_thread,
                        )
                        return
                    raise
            if not used_fallback:
                source_label = (
                    f"stooq-only:{stooq_symbol}" if stooq_only else f"stooq:{stooq_symbol}"
                )
                base_symbol = stooq_symbol.split(".", 1)[0] if "." in stooq_symbol else stooq_symbol
                symbol_override = base_symbol.upper()
        elif _is_yahoo_source(source_path):
            yahoo_symbol = _yahoo_source_symbol(source_path, dataset)
            base_symbol = yahoo_symbol.split(".", 1)[0] if yahoo_symbol.endswith(".HK") else yahoo_symbol
            try:
                path = _fetch_yahoo_csv(yahoo_symbol, job.dataset_id, dataset_name)
            except RuntimeError as exc:
                code = str(exc)
                if code == "YAHOO_RATE_LIMIT":
                    _schedule_retry(
                        session,
                        job,
                        reason="YAHOO_RATE_LIMIT",
                        min_delay=int(YAHOO_RATE_LIMIT_WINDOW.total_seconds()),
                        status="rate_limited",
                        spawn_thread=spawn_retry_thread,
                    )
                    return
                elif code == "YAHOO_NOT_FOUND":
                    job.status = "not_found"
                    job.message = "Yahoo 未覆盖该代码"
                else:
                    _schedule_retry(
                        session,
                        job,
                        reason=code,
                        spawn_thread=spawn_retry_thread,
                    )
                    return
                job.ended_at = datetime.utcnow()
                record_audit(
                    session,
                    action="data.sync.blocked",
                    resource_type="data_sync_job",
                    resource_id=job.id,
                    detail={"dataset_id": job.dataset_id, "reason": job.message},
                )
                session.commit()
                return
            source_label = f"yahoo:{yahoo_symbol}"
            symbol_override = base_symbol.upper()
        elif _is_alpha_source(source_path):
            alpha_symbol = _alpha_source_symbol(source_path, dataset)
            base_symbol = alpha_symbol.split(".", 1)[0] if alpha_symbol.endswith(".HK") else alpha_symbol
            exclude_map = _load_alpha_exclude_symbols(_get_data_root())
            exclude_reason = exclude_map.get(alpha_symbol.upper()) if exclude_map else None
            if exclude_reason is not None:
                job.status = "skipped"
                job.message = f"skip=alpha_exclude; reason={exclude_reason or 'alpha_exclude'}"
                job.ended_at = datetime.utcnow()
                record_audit(
                    session,
                    action="data.sync.skip",
                    resource_type="data_sync_job",
                    resource_id=job.id,
                    detail={
                        "dataset_id": job.dataset_id,
                        "symbol": alpha_symbol,
                        "reason": exclude_reason or "alpha_exclude",
                    },
                )
                session.commit()
                return
            alpha_fetch_cfg = load_alpha_fetch_config(_get_data_root())
            alpha_incremental_enabled = bool(
                alpha_fetch_cfg.get(
                    "alpha_incremental_enabled", DEFAULT_ALPHA_INCREMENTAL_ENABLED
                )
            )
            alpha_compact_days = int(
                alpha_fetch_cfg.get("alpha_compact_days") or DEFAULT_ALPHA_COMPACT_DAYS
            )
            alpha_coverage_end = _parse_date(dataset.coverage_end if dataset else None)
            alpha_latest_complete = _latest_complete_business_day()
            gap_days = None
            if alpha_coverage_end:
                gap_days = (alpha_latest_complete - alpha_coverage_end).days
                if gap_days < 0:
                    gap_days = 0
            outputsize = "full"
            if (
                alpha_incremental_enabled
                and not reset_history
                and alpha_coverage_end
                and gap_days is not None
            ):
                outputsize = "compact" if gap_days <= alpha_compact_days else "full"
            alpha_outputsize = outputsize
            alpha_meta = {
                "alpha_outputsize": outputsize,
                "gap_days": gap_days,
                "coverage_end": alpha_coverage_end.isoformat() if alpha_coverage_end else None,
                "latest_complete": alpha_latest_complete.isoformat()
                if alpha_latest_complete
                else None,
                "alpha_incremental_enabled": alpha_incremental_enabled,
                "alpha_compact_days": alpha_compact_days,
                "alpha_compact_fallback": False,
            }
            try:
                path = _fetch_alpha_csv_with_retry(
                    alpha_symbol,
                    job.dataset_id,
                    dataset_name,
                    outputsize=outputsize,
                )
            except RuntimeError as exc:
                code = str(exc)
                if code in {"ALPHA_RATE_LIMIT", "ALPHA_PREMIUM", "ALPHA_LOCK_BUSY"}:
                    config = load_alpha_rate_config(_get_data_root())
                    min_delay = int(config.get("rate_limit_sleep") or DEFAULT_RATE_LIMIT_SLEEP)
                    tune_hint = (
                        f"tune=max_rpm={config.get('max_rpm')};"
                        f"min_delay={config.get('min_delay_seconds')}"
                    )
                    _schedule_retry(
                        session,
                        job,
                        reason=f"{code}; {tune_hint}",
                        min_delay=min_delay,
                        status="rate_limited",
                        spawn_thread=spawn_retry_thread,
                    )
                    return
                elif code == "ALPHA_NOT_FOUND":
                    _append_alpha_exclude_symbol(
                        _get_data_root(), alpha_symbol, "alpha_not_covered"
                    )
                    job.status = "not_found"
                    job.message = "Alpha Vantage 未覆盖该代码"
                elif code == "ALPHA_KEY_MISSING":
                    job.status = "failed"
                    job.message = "Alpha Vantage API Key 未配置"
                else:
                    _schedule_retry(
                        session,
                        job,
                        reason=code,
                        spawn_thread=spawn_retry_thread,
                    )
                    return
                job.ended_at = datetime.utcnow()
                record_audit(
                    session,
                    action="data.sync.blocked",
                    resource_type="data_sync_job",
                    resource_id=job.id,
                    detail={"dataset_id": job.dataset_id, "reason": job.message},
                )
                session.commit()
                return
            source_label = f"alpha:{alpha_symbol}"
            symbol_override = base_symbol.upper()
        else:
            path = _resolve_path(source_path)
            data_root = _get_data_root()
            if not str(path).startswith(str(data_root)):
                raise RuntimeError("文件路径不在允许范围内")
            if not path.exists():
                raise RuntimeError("文件路径不存在")

        symbol_hint = symbol_override or dataset_name
        lean_root = _get_lean_root()
        canonical_symbol, map_path, _ = _resolve_canonical_symbol(symbol_hint, lean_root)
        symbol_override = canonical_symbol
        factor_path = _resolve_factor_path(dataset, canonical_symbol)
        factors: list[tuple[date, float]] = []
        alpha_factors: list[tuple[date, float]] = []
        existing_factors: list[tuple[date, float]] = []
        cache_factor_path = _factor_cache_path(canonical_symbol)
        is_alpha_source = _is_alpha_source(source_path)
        if ALPHA_ONLY_PRICES and not is_alpha_source:
            factor_source = "alpha_only_skip"
        else:
            if is_alpha_source:
                alpha_factors = _build_factors_from_alpha_csv(path)
                existing_factors = _load_factor_file(cache_factor_path)
                if alpha_outputsize == "compact":
                    if existing_factors:
                        factors = _merge_factor_history(existing_factors, alpha_factors)
                        if factors:
                            factor_source = "alpha_compact_merge"
                    else:
                        factors = alpha_factors
                        if factors:
                            factor_source = "alpha_compact_only"
                else:
                    factors = alpha_factors
                    if factors:
                        factor_source = "alpha"
            if not factors:
                factors = _load_factor_file(factor_path)
                if factors:
                    factor_source = "alpha_cache" if ALPHA_ONLY_PRICES else "lean"
            if not factors and not ALPHA_ONLY_PRICES:
                factors = _build_factors_from_yahoo(canonical_symbol, dataset)
                if factors:
                    factor_source = "yahoo"

        _set_job_stage(session, job, "normalize", 0.6)
        source_files = _collect_csv_files(path)
        records, raw_rows, _, _, issues = _normalize_records(
            source_files, job.date_column, dataset_name, symbol_override
        )
        if (
            alpha_outputsize == "compact"
            and alpha_symbol
            and alpha_coverage_end
            and records
        ):
            earliest_date = min(ts.date() for ts, _ in records)
            if earliest_date > alpha_coverage_end:
                alpha_compact_fallback = True
                alpha_outputsize = "full"
                if alpha_meta is not None:
                    alpha_meta["alpha_outputsize"] = "full"
                    alpha_meta["alpha_compact_fallback"] = True
                path = _fetch_alpha_csv_with_retry(
                    alpha_symbol,
                    job.dataset_id,
                    dataset_name,
                    outputsize="full",
                )
                source_files = _collect_csv_files(path)
                records, raw_rows, _, _, issues = _normalize_records(
                    source_files, job.date_column, dataset_name, symbol_override
                )
        if not records:
            raise RuntimeError("未找到可用记录")

        if reset_history:
            normalized_path.unlink(missing_ok=True)
            curated_path.unlink(missing_ok=True)
            adjusted_path.unlink(missing_ok=True)
        last_norm_dt = _get_last_date(normalized_path)
        norm_records = [
            record for record in records if last_norm_dt is None or record[0] > last_norm_dt
        ]
        _append_normalized(normalized_path, [row for _, row in norm_records])

        last_cur_dt = _get_last_date(curated_path)
        if reset_history:
            last_cur_dt = None
        curated_records = {} if reset_history else _load_curated(curated_path)
        for timestamp, row in records:
            if last_cur_dt is not None and timestamp < last_cur_dt:
                continue
            existing = curated_records.get(timestamp)
            if existing is None or _row_score(row) >= _row_score(existing):
                curated_records[timestamp] = row
        _write_curated(curated_path, curated_records)
        if is_alpha_source and alpha_outputsize == "compact" and curated_records:
            earliest_data = min(curated_records.keys()).date()
            earliest_factor = factors[0][0] if factors else None
            if earliest_factor is None or earliest_factor > earliest_data:
                full_path = _fetch_alpha_csv_with_retry(
                    alpha_symbol,
                    job.dataset_id,
                    dataset_name,
                    outputsize="full",
                )
                full_factors = _build_factors_from_alpha_csv(full_path)
                if full_factors:
                    factors = full_factors
                    factor_source = "alpha_full"
                    alpha_compact_fallback = True
                    if alpha_meta is not None:
                        alpha_meta["alpha_outputsize"] = "full"
                        alpha_meta["alpha_compact_fallback"] = True
        if factors and factor_source in {
            "alpha",
            "alpha_compact_merge",
            "alpha_compact_only",
            "alpha_full",
            "yahoo",
        }:
            _write_factor_file(cache_factor_path, factors)
        adjusted_records = _apply_price_factors(curated_records, factors)
        adjusted_records, cliff_count = _sanitize_cliffs(adjusted_records)
        lean_adjusted_path = None
        if adjusted_records:
            _write_curated(adjusted_path, adjusted_records)
            lean_adjusted_root = _get_data_root() / "lean_adjusted"
            base_lean_root = _get_lean_root()
            _ensure_support_directory(lean_adjusted_root, base_lean_root, "symbol-properties")
            _ensure_support_directory(lean_adjusted_root, base_lean_root, "market-hours")
            lean_adjusted_path = _export_lean_daily_to_root(
                dataset, adjusted_records, dataset_name, lean_adjusted_root
            )
        _set_job_stage(session, job, "finalize", 0.9)
        snapshot_path = _write_snapshot(job.dataset_id, dataset_name, curated_records)
        lean_path = _export_lean_daily(dataset, curated_records, dataset_name)

        coverage_start = min(curated_records.keys()).date().isoformat() if curated_records else None
        coverage_end = max(curated_records.keys()).date().isoformat() if curated_records else None

        job.rows_scanned = raw_rows
        job.coverage_start = coverage_start
        job.coverage_end = coverage_end
        job.normalized_path = str(normalized_path)
        job.output_path = str(curated_path)
        job.snapshot_path = str(snapshot_path) if snapshot_path else None
        job.lean_path = str(lean_path) if lean_path else None
        job.adjusted_path = str(adjusted_path) if adjusted_records else None
        job.lean_adjusted_path = str(lean_adjusted_path) if lean_adjusted_path else None
        message_parts = [
            f"raw_rows={raw_rows}",
            f"normalized_new={len(norm_records)}",
            f"curated_rows={len(curated_records)}",
        ]
        if source_label:
            message_parts.append(f"source={source_label}")
        if alpha_meta:
            outputsize = alpha_meta.get("alpha_outputsize")
            if outputsize:
                message_parts.append(f"alpha_outputsize={outputsize}")
            gap_days = alpha_meta.get("gap_days")
            if gap_days is not None:
                message_parts.append(f"gap_days={gap_days}")
            if alpha_meta.get("coverage_end"):
                message_parts.append(f"coverage_end={alpha_meta.get('coverage_end')}")
            if alpha_meta.get("latest_complete"):
                message_parts.append(f"latest_complete={alpha_meta.get('latest_complete')}")
            if alpha_meta.get("alpha_compact_fallback"):
                message_parts.append("alpha_compact_fallback=1")
        if map_path:
            message_parts.append(f"map=ok({map_path.name})")
        else:
            message_parts.append("map=missing")
        if factor_source in {"alpha", "alpha_cache"}:
            message_parts.append("factor=alpha")
        elif factor_source == "yahoo":
            message_parts.append("factor=yahoo")
        elif factor_source == "lean":
            message_parts.append("factor=lean")
        elif factors:
            message_parts.append("factor=ok")
        else:
            message_parts.append("factor=missing")
        if snapshot_path:
            message_parts.append("snapshot=ok")
        if lean_path:
            message_parts.append("lean=ok")
        if adjusted_records:
            message_parts.append("adjusted=ok")
        if lean_adjusted_path:
            message_parts.append("lean_adjusted=ok")
        if cliff_count:
            message_parts.append(f"cliff_sanitized={cliff_count}")
        if issues:
            message_parts.append("issues=" + "；".join(issues))
        job.message = "; ".join(message_parts)

        if dataset:
            if job.coverage_start and (
                not dataset.coverage_start
                or job.coverage_start < dataset.coverage_start
            ):
                dataset.coverage_start = job.coverage_start
            if job.coverage_end and (
                not dataset.coverage_end
                or job.coverage_end > dataset.coverage_end
            ):
                dataset.coverage_end = job.coverage_end
            dataset.updated_at = datetime.utcnow()

        job.status = "success"
        job.retry_count = 0
        job.next_retry_at = None
        job.ended_at = datetime.utcnow()
        record_audit(
            session,
            action="data.sync.success",
            resource_type="data_sync_job",
            resource_id=job.id,
            detail={
                "dataset_id": job.dataset_id,
                "rows_scanned": job.rows_scanned,
                "normalized_path": job.normalized_path,
                "output_path": job.output_path,
                "snapshot_path": job.snapshot_path,
                "lean_path": job.lean_path,
                "adjusted_path": job.adjusted_path,
                "lean_adjusted_path": job.lean_adjusted_path,
            },
        )
        session.commit()
    except Exception as exc:
        job = session.get(DataSyncJob, job_id)
        if job:
            job.status = "failed"
            job.message = str(exc)
            job.ended_at = datetime.utcnow()
            record_audit(
                session,
                action="data.sync.failed",
                resource_type="data_sync_job",
                resource_id=job.id,
                detail={"dataset_id": job.dataset_id, "error": str(exc)},
            )
            session.commit()
    finally:
        session.close()


@router.post("/actions/fetch", response_model=DatasetFetchOut)
def fetch_dataset(payload: DatasetFetchRequest, background_tasks: BackgroundTasks):
    raw_symbol = payload.symbol.strip()
    if not raw_symbol:
        raise HTTPException(status_code=400, detail="缺少股票代码")
    symbol = _normalize_symbol(raw_symbol)
    if not symbol or symbol == "UNKNOWN":
        raise HTTPException(status_code=400, detail="股票代码无效")

    vendor = (payload.vendor or "alpha").strip().lower()
    if vendor != "alpha":
        raise HTTPException(status_code=400, detail="当前仅支持 Alpha Vantage 数据源")

    frequency = (payload.frequency or "daily").strip().lower()
    if frequency not in {"daily", "minute"}:
        raise HTTPException(status_code=400, detail="不支持的频率")
    if frequency != "daily":
        raise HTTPException(status_code=400, detail="当前数据源仅支持日线数据")

    region = (payload.region or "US").strip().upper()
    asset_class = (payload.asset_class or "Equity").strip()
    vendor_label = _format_title(vendor)
    frequency_label = "Daily" if frequency == "daily" else "Minute"
    dataset_name = (
        payload.name.strip()
        if payload.name and payload.name.strip()
        else f"{vendor_label}_{symbol.upper()}_{frequency_label}"
    )
    source_path = f"{vendor}:{symbol.lower()}"

    created = False
    with get_session() as session:
        dataset = (
            session.query(Dataset)
            .filter(
                Dataset.source_path == source_path,
                Dataset.vendor == vendor_label,
                Dataset.frequency == frequency,
                Dataset.region == region,
            )
            .first()
        )
        if not dataset:
            dataset = session.query(Dataset).filter(Dataset.name == dataset_name).first()

        if not dataset:
            dataset = Dataset(
                name=dataset_name,
                vendor=vendor_label,
                asset_class=asset_class,
                region=region,
                frequency=frequency,
                source_path=source_path,
            )
            session.add(dataset)
            session.commit()
            session.refresh(dataset)
            created = True
            record_audit(
                session,
                action="dataset.create",
                resource_type="dataset",
                resource_id=dataset.id,
                detail={"name": dataset.name},
            )
            session.commit()
        else:
            updated = False
            if not dataset.vendor and vendor_label:
                dataset.vendor = vendor_label
                updated = True
            if not dataset.asset_class and asset_class:
                dataset.asset_class = asset_class
                updated = True
            if not dataset.region and region:
                dataset.region = region
                updated = True
            if not dataset.frequency and frequency:
                dataset.frequency = frequency
                updated = True
            if not dataset.source_path and source_path:
                dataset.source_path = source_path
                updated = True
            if updated:
                dataset.updated_at = datetime.utcnow()
                record_audit(
                    session,
                    action="dataset.update",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    detail={"source_path": source_path},
                )
                session.commit()

        record_audit(
            session,
            action="dataset.fetch",
            resource_type="dataset",
            resource_id=dataset.id,
            detail={
                "symbol": symbol.upper(),
                "vendor": vendor_label,
                "frequency": frequency,
                "region": region,
                "created": created,
            },
        )
        session.commit()

    job_out = None
    if payload.auto_sync:
        job = create_sync_job(
            dataset.id,
            DataSyncCreate(
                source_path=source_path,
                date_column="date",
                stooq_only=payload.stooq_only,
            ),
            background_tasks,
        )
        job_out = DataSyncOut.model_validate(job, from_attributes=True)

    return DatasetFetchOut(
        dataset=DatasetOut.model_validate(dataset, from_attributes=True),
        job=job_out,
        created=created,
    )


@router.post("/actions/fetch-listing", response_model=DatasetListingFetchOut)
def fetch_listing_datasets(
    payload: DatasetListingFetchRequest, background_tasks: BackgroundTasks
):
    vendor = (payload.vendor or "alpha").strip().lower()
    if vendor != "alpha":
        raise HTTPException(status_code=400, detail="当前仅支持 Alpha Vantage 数据源")
    frequency = (payload.frequency or "daily").strip().lower()
    if frequency != "daily":
        raise HTTPException(status_code=400, detail="当前仅支持日线数据")

    status_filter = (payload.status or "all").strip().lower()
    if status_filter not in {"all", "active", "delisted"}:
        raise HTTPException(status_code=400, detail="状态参数无效")

    asset_types = payload.asset_types
    if asset_types:
        asset_type_filter = {item.strip().upper() for item in asset_types if item.strip()}
    else:
        asset_type_filter = {"STOCK", "ETF"}

    paths = _resolve_listing_paths(payload.source_path)
    rows = _load_listing_rows(paths)
    if not rows:
        raise HTTPException(status_code=404, detail="listing 文件不存在或为空")

    symbol_map: dict[str, dict[str, str]] = {}
    for row in rows:
        symbol = _normalize_symbol(row.get("symbol", "")).upper()
        if not symbol or symbol == "UNKNOWN":
            continue
        row_status = (row.get("status") or "").strip().lower()
        if status_filter != "all" and row_status != status_filter:
            continue
        asset_type = (row.get("assetType") or "").strip().upper() or "UNKNOWN"
        if asset_type_filter and asset_type not in asset_type_filter:
            continue
        if symbol not in symbol_map:
            symbol_map[symbol] = {"symbol": symbol, "asset_type": asset_type}

    items = sorted(symbol_map.values(), key=lambda item: item["symbol"])
    total_symbols = len(items)
    offset = max(payload.offset, 0)
    limit = max(payload.limit, 0)
    batch = items[offset:] if limit == 0 else items[offset : offset + limit]
    selected_symbols = len(batch)
    next_offset = offset + selected_symbols if offset + selected_symbols < total_symbols else None

    vendor_label = _format_title(vendor)
    frequency_label = "Daily"
    region = (payload.region or "US").strip().upper()

    created = 0
    reused = 0
    queued = 0

    with get_session() as session:
        for item in batch:
            symbol = item["symbol"]
            asset_type = item["asset_type"]
            asset_class = "ETF" if asset_type == "ETF" else "Equity"
            source_path = f"{vendor}:{symbol.lower()}"
            dataset_name = f"{vendor_label}_{symbol}_{frequency_label}"
            dataset = (
                session.query(Dataset)
                .filter(
                    Dataset.source_path == source_path,
                    Dataset.vendor == vendor_label,
                    Dataset.frequency == frequency,
                    Dataset.region == region,
                )
                .first()
            )
            if not dataset:
                dataset = session.query(Dataset).filter(Dataset.name == dataset_name).first()

            if dataset and payload.only_missing:
                reused += 1
                continue

            if not dataset:
                dataset = Dataset(
                    name=dataset_name,
                    vendor=vendor_label,
                    asset_class=asset_class,
                    region=region,
                    frequency=frequency,
                    source_path=source_path,
                )
                session.add(dataset)
                session.commit()
                session.refresh(dataset)
                created += 1
                record_audit(
                    session,
                    action="dataset.create",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    detail={"name": dataset.name, "source": "listing"},
                )
                session.commit()
            else:
                reused += 1
                updated = False
                if asset_class and dataset.asset_class != asset_class:
                    dataset.asset_class = asset_class
                    updated = True
                if region and dataset.region != region:
                    dataset.region = region
                    updated = True
                if not dataset.frequency and frequency:
                    dataset.frequency = frequency
                    updated = True
                if not dataset.source_path and source_path:
                    dataset.source_path = source_path
                    updated = True
                if updated:
                    dataset.updated_at = datetime.utcnow()
                    record_audit(
                        session,
                        action="dataset.update",
                        resource_type="dataset",
                        resource_id=dataset.id,
                        detail={"source_path": source_path},
                    )
                    session.commit()

            if payload.auto_sync:
                job = create_sync_job(
                    dataset.id,
                    DataSyncCreate(
                        source_path=source_path,
                        date_column="date",
                        reset_history=payload.reset_history,
                        auto_run=payload.auto_run,
                    ),
                    background_tasks,
                )
                if job:
                    queued += 1

    return DatasetListingFetchOut(
        total_symbols=total_symbols,
        selected_symbols=selected_symbols,
        created=created,
        reused=reused,
        queued=queued,
        offset=offset,
        next_offset=next_offset,
    )


@router.get("/theme-coverage", response_model=DatasetThemeCoverageOut)
def get_theme_coverage(theme_key: str = Query(..., min_length=1)):
    normalized = theme_key.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="缺少主题编码")
    with get_session() as session:
        from app.routes import universe as universe_routes

        universe_routes._ensure_universe_memberships(session)
        theme_rows = (
            session.query(UniverseMembership.symbol)
            .filter(UniverseMembership.category == normalized)
            .distinct()
            .order_by(UniverseMembership.symbol.asc())
            .all()
        )
        theme_symbols = [row[0] for row in theme_rows]
        theme_label = (
            session.query(func.max(UniverseMembership.category_label))
            .filter(UniverseMembership.category == normalized)
            .scalar()
        )
        updated_at = (
            session.query(func.max(UniverseMembership.source_updated_at))
            .filter(UniverseMembership.category == normalized)
            .scalar()
        )
        dataset_symbols = {
            _dataset_symbol(dataset)
            for dataset in session.query(Dataset).all()
            if _dataset_symbol(dataset)
        }
        theme_symbol_set = {symbol.upper() for symbol in theme_symbols}
        covered = sorted(theme_symbol_set & dataset_symbols)
        missing = sorted(theme_symbol_set - dataset_symbols)

    return DatasetThemeCoverageOut(
        theme_key=normalized,
        theme_label=theme_label or normalized,
        total_symbols=len(theme_symbols),
        covered_symbols=len(covered),
        missing_symbols=missing,
        updated_at=updated_at,
    )


@router.post("/actions/fetch-theme", response_model=DatasetThemeFetchOut)
def fetch_theme_datasets(payload: DatasetThemeFetchRequest, background_tasks: BackgroundTasks):
    theme_key = payload.theme_key.strip()
    if not theme_key:
        raise HTTPException(status_code=400, detail="缺少主题编码")
    vendor = (payload.vendor or "alpha").strip().lower()
    if vendor != "alpha":
        raise HTTPException(status_code=400, detail="当前仅支持 Alpha Vantage 数据源")
    frequency = (payload.frequency or "daily").strip().lower()
    if frequency not in {"daily", "minute"}:
        raise HTTPException(status_code=400, detail="不支持的频率")
    if vendor == "alpha" and frequency != "daily":
        raise HTTPException(status_code=400, detail="Alpha Vantage 仅支持日线数据")

    region = (payload.region or "US").strip().upper()
    asset_class = (payload.asset_class or "Equity").strip()
    vendor_label = _format_title(vendor)
    frequency_label = "Daily" if frequency == "daily" else "Minute"

    created = 0
    reused = 0
    queued = 0
    sync_queue: list[tuple[int, str]] = []

    with get_session() as session:
        from app.routes import universe as universe_routes

        universe_routes._ensure_universe_memberships(session)
        rows = [
            (row[0], row[1], row[2])
            for row in (
                session.query(
                    UniverseMembership.symbol,
                    UniverseMembership.region,
                    UniverseMembership.asset_class,
                )
                .filter(UniverseMembership.category == theme_key)
                .distinct()
                .order_by(UniverseMembership.symbol.asc())
                .all()
            )
        ]
        for symbol, region_value, asset_value in rows:
            region = (region_value or default_region or "US").strip().upper()
            asset_class = (asset_value or default_asset_class or "Equity").strip()
            source_path = f"{vendor}:{symbol.lower()}"
            dataset_name = f"{vendor_label}_{symbol}_{frequency_label}"
            dataset = (
                session.query(Dataset)
                .filter(
                    Dataset.source_path == source_path,
                    Dataset.vendor == vendor_label,
                    Dataset.frequency == frequency,
                    Dataset.region == region,
                )
                .first()
            )
            if not dataset:
                dataset = session.query(Dataset).filter(Dataset.name == dataset_name).first()

            if dataset and payload.only_missing:
                reused += 1
                continue

            if not dataset:
                dataset = Dataset(
                    name=dataset_name,
                    vendor=vendor_label,
                    asset_class=asset_class,
                    region=region,
                    frequency=frequency,
                    source_path=source_path,
                )
                session.add(dataset)
                session.commit()
                session.refresh(dataset)
                created += 1
                record_audit(
                    session,
                    action="dataset.create",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    detail={"name": dataset.name, "theme": theme_key},
                )
                session.commit()
            else:
                reused += 1
                updated = False
                if not dataset.vendor and vendor_label:
                    dataset.vendor = vendor_label
                    updated = True
                if asset_class and dataset.asset_class != asset_class:
                    dataset.asset_class = asset_class
                    updated = True
                if region and dataset.region != region:
                    dataset.region = region
                    updated = True
                if not dataset.frequency and frequency:
                    dataset.frequency = frequency
                    updated = True
                if not dataset.source_path and source_path:
                    dataset.source_path = source_path
                    updated = True
                if updated:
                    dataset.updated_at = datetime.utcnow()
                    record_audit(
                        session,
                        action="dataset.update",
                        resource_type="dataset",
                        resource_id=dataset.id,
                        detail={"source_path": source_path},
                    )
                    session.commit()

            if payload.auto_sync:
                sync_queue.append((dataset.id, source_path))

    if payload.auto_sync:
        for dataset_id, source_path in sync_queue:
            job = create_sync_job(
                dataset_id,
                DataSyncCreate(source_path=source_path, date_column="date"),
                background_tasks,
            )
            if job:
                queued += 1

    return DatasetThemeFetchOut(
        theme_key=theme_key,
        total_symbols=len(rows),
        created=created,
        reused=reused,
        queued=queued,
    )


@router.post("", response_model=DatasetOut)
def create_dataset(payload: DatasetCreate):
    with get_session() as session:
        existing = session.query(Dataset).filter(Dataset.name == payload.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="数据集已存在")
        dataset = Dataset(
            name=payload.name,
            vendor=payload.vendor,
            asset_class=payload.asset_class,
            region=payload.region,
            frequency=payload.frequency,
            coverage_start=payload.coverage_start,
            coverage_end=payload.coverage_end,
            source_path=payload.source_path,
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        record_audit(
            session,
            action="dataset.create",
            resource_type="dataset",
            resource_id=dataset.id,
            detail={"name": dataset.name},
        )
        session.commit()
        return dataset


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int):
    with get_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")
        return dataset


@router.get("/{dataset_id}/series", response_model=DatasetSeriesOut)
def get_dataset_series(
    dataset_id: int,
    mode: str = Query("both"),
    start: str | None = None,
    end: str | None = None,
):
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"raw", "adjusted", "both"}:
        raise HTTPException(status_code=400, detail="不支持的模式")
    with get_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")

    start_dt = _parse_datetime_bound(start, is_end=False)
    end_dt = _parse_datetime_bound(end, is_end=True)

    candles: list[dict] = []
    adjusted: list[dict] = []
    if normalized_mode in {"raw", "both"}:
        candles = _load_candles(_series_path(dataset, adjusted=False), start_dt, end_dt)
    if normalized_mode in {"adjusted", "both"}:
        adjusted = _load_adjusted_line(
            _series_path(dataset, adjusted=True),
            start_dt,
            end_dt,
        )

    return DatasetSeriesOut(
        dataset_id=dataset.id,
        mode=normalized_mode,
        start=start,
        end=end,
        candles=candles,
        adjusted=adjusted,
    )


@router.post("/actions/batch-delete", response_model=DatasetDeleteOut)
def delete_datasets(payload: DatasetDeleteRequest):
    dataset_ids = [int(value) for value in payload.dataset_ids if value is not None]
    if not dataset_ids:
        raise HTTPException(status_code=400, detail="缺少数据集 ID")
    unique_ids = sorted(set(dataset_ids))

    data_root = _get_data_root()
    lean_root = _get_lean_root()
    allowed_roots = [data_root, lean_root, data_root / "lean_adjusted"]

    deleted_files: list[str] = []
    missing_ids: list[int] = []
    found_ids: list[int] = []
    paths_to_delete: set[Path] = set()

    with get_session() as session:
        datasets = session.query(Dataset).filter(Dataset.id.in_(unique_ids)).all()
        found_lookup = {dataset.id: dataset for dataset in datasets}
        missing_ids = [dataset_id for dataset_id in unique_ids if dataset_id not in found_lookup]
        found_ids = sorted(found_lookup.keys())

        jobs = (
            session.query(DataSyncJob)
            .filter(DataSyncJob.dataset_id.in_(found_ids))
            .all()
        )
        for job in jobs:
            for path_value in (
                job.normalized_path,
                job.output_path,
                job.snapshot_path,
                job.lean_path,
                job.adjusted_path,
                job.lean_adjusted_path,
            ):
                if path_value:
                    paths_to_delete.add(Path(path_value))

        for dataset in datasets:
            safe_name = _safe_name(dataset.name)
            output_name = f"{dataset.id}_{safe_name}.csv"
            for folder in ("normalized", "curated", "curated_adjusted"):
                paths_to_delete.add(data_root / folder / output_name)
            paths_to_delete.add(data_root / "raw" / "stooq" / output_name)
            paths_to_delete.add(data_root / "curated_versions" / f"{dataset.id}_{safe_name}")

        if found_ids:
            session.query(DataSyncJob).filter(
                DataSyncJob.dataset_id.in_(found_ids)
            ).delete(synchronize_session=False)
            for dataset_id in found_ids:
                record_audit(
                    session,
                    action="dataset.delete",
                    resource_type="dataset",
                    resource_id=dataset_id,
                    detail={"dataset_id": dataset_id},
                )
            session.query(Dataset).filter(Dataset.id.in_(found_ids)).delete(
                synchronize_session=False
            )
            session.commit()

    for path in sorted(paths_to_delete, key=lambda item: str(item)):
        if _safe_delete_path(path, allowed_roots):
            deleted_files.append(str(path))

    return DatasetDeleteOut(
        deleted_ids=found_ids,
        missing_ids=missing_ids,
        deleted_files=deleted_files,
    )

@router.put("/{dataset_id}", response_model=DatasetOut)
def update_dataset(dataset_id: int, payload: DatasetUpdate):
    with get_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")
        updates = payload.model_dump(exclude_unset=True)
        if "name" in updates and updates["name"]:
            existing = (
                session.query(Dataset)
                .filter(Dataset.name == updates["name"], Dataset.id != dataset_id)
                .first()
            )
            if existing:
                raise HTTPException(status_code=409, detail="数据集名称已存在")
        for key, value in updates.items():
            setattr(dataset, key, value)
        dataset.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(dataset)
        record_audit(
            session,
            action="dataset.update",
            resource_type="dataset",
            resource_id=dataset.id,
            detail=updates,
        )
        session.commit()
        return dataset


@router.get("/{dataset_id}/quality", response_model=DatasetQualityOut)
def get_dataset_quality(dataset_id: int):
    with get_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")

    issues: list[str] = []
    data_points = None
    min_interval_days = None
    curated_path = _series_path(dataset, adjusted=False)
    if curated_path.exists():
        min_interval_days, data_points = _calc_min_interval(curated_path)
    start = _parse_date(dataset.coverage_start)
    end = _parse_date(dataset.coverage_end)
    coverage_days = None
    expected_points = None

    if not start or not end:
        issues.append("覆盖起止日期不完整")
    elif start > end:
        issues.append("覆盖开始日期晚于结束日期")
    else:
        coverage_days = (end - start).days + 1
        business_days = _count_business_days(start, end)
        freq = (dataset.frequency or "").lower()
        if freq in {"d", "day", "daily"}:
            expected_points = business_days
        elif freq in {"m", "min", "minute", "1min"}:
            expected_points = business_days * 390
        elif freq:
            issues.append("暂不支持该频率的估算")
        else:
            issues.append("频率字段为空")

    status = "ok" if not issues else "warn"
    return DatasetQualityOut(
        dataset_id=dataset.id,
        frequency=dataset.frequency,
        coverage_start=dataset.coverage_start,
        coverage_end=dataset.coverage_end,
        coverage_days=coverage_days,
        expected_points_estimate=expected_points,
        data_points=data_points,
        min_interval_days=min_interval_days,
        issues=issues,
        status=status,
    )


@router.post("/{dataset_id}/quality/scan", response_model=DatasetQualityScanOut)
def scan_dataset_quality(dataset_id: int, payload: DatasetQualityScanRequest):
    with get_session() as session:
        dataset = session.get(Dataset, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")

    data_root = _get_data_root()
    path = _resolve_path(payload.file_path)
    if not str(path).startswith(str(data_root)):
        raise HTTPException(status_code=400, detail="文件路径不在允许范围内")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    issues: list[str] = []
    rows = 0
    null_close = 0
    duplicate_timestamps = 0
    timestamps_seen: set[str] = set()
    dates_seen: set[date] = set()
    min_dt: datetime | None = None
    max_dt: datetime | None = None
    returns: list[float] = []
    last_close: float | None = None

    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV 缺少表头")
        if payload.date_column not in reader.fieldnames:
            raise HTTPException(status_code=400, detail="未找到日期列")
        if payload.close_column not in reader.fieldnames:
            issues.append("未找到收盘价列，跳过异常收益检测")

        for row in reader:
            rows += 1
            raw_time = row.get(payload.date_column, "").strip()
            parsed = _parse_datetime(raw_time)
            if not parsed:
                continue
            if min_dt is None or parsed < min_dt:
                min_dt = parsed
            if max_dt is None or parsed > max_dt:
                max_dt = parsed
            date_key = parsed.date()
            dates_seen.add(date_key)
            ts_key = parsed.isoformat()
            if ts_key in timestamps_seen:
                duplicate_timestamps += 1
            else:
                timestamps_seen.add(ts_key)

            close_raw = row.get(payload.close_column) if payload.close_column else None
            if close_raw is None or close_raw == "":
                null_close += 1
                continue
            try:
                close_val = float(close_raw)
            except ValueError:
                null_close += 1
                continue
            if last_close is not None and last_close != 0:
                returns.append((close_val - last_close) / last_close)
            last_close = close_val

    coverage_start = min_dt.date().isoformat() if min_dt else None
    coverage_end = max_dt.date().isoformat() if max_dt else None
    missing_days = None
    missing_ratio = None

    freq = (payload.frequency or dataset.frequency or "").lower()
    if min_dt and max_dt:
        expected_days = _count_business_days(min_dt.date(), max_dt.date())
        missing_days = max(expected_days - len(dates_seen), 0)
        missing_ratio = (
            missing_days / expected_days if expected_days else None
        )
        if freq in {"m", "min", "minute", "1min"} and rows > expected_days * 390:
            issues.append("疑似包含盘前/盘后数据")
    else:
        issues.append("无法解析时间范围")

    outlier_returns = 0
    max_abs_return = None
    if returns:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = variance ** 0.5
        max_abs_return = max(abs(r) for r in returns)
        for r in returns:
            if std > 0 and abs(r - mean) > 3 * std and abs(r) > 0.1:
                outlier_returns += 1
    else:
        if payload.close_column in reader.fieldnames:
            issues.append("收益序列不足，无法检测异常")

    if missing_days is not None and missing_days > 0:
        issues.append("存在缺失交易日")
    if duplicate_timestamps > 0:
        issues.append("存在重复时间戳")
    if null_close > 0:
        issues.append("存在空收盘价记录")

    return DatasetQualityScanOut(
        dataset_id=dataset.id,
        file_path=str(path),
        rows=rows,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        missing_days=missing_days,
        missing_ratio=missing_ratio,
        null_close_rows=null_close,
        duplicate_timestamps=duplicate_timestamps,
        outlier_returns=outlier_returns,
        max_abs_return=max_abs_return,
        issues=issues,
    )
