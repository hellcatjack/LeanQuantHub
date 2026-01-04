from __future__ import annotations

import csv
import threading
import json
import math
import re
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import func

from app.db import SessionLocal, get_session
from app.models import DataSyncJob, Dataset, UniverseMembership
from app.core.config import settings
from app.schemas import (
    DataSyncCreate,
    DataSyncBatchRequest,
    DataSyncOut,
    DataSyncPageOut,
    DatasetCreate,
    DatasetDeleteOut,
    DatasetDeleteRequest,
    DatasetFetchOut,
    DatasetFetchRequest,
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

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

MAX_PAGE_SIZE = 200
ACTIVE_SYNC_STATUSES = {"queued", "running", "rate_limited"}
STOOQ_RATE_LIMIT_WINDOW = timedelta(hours=24)
_stooq_rate_limited_until: datetime | None = None

YAHOO_RATE_LIMIT_WINDOW = timedelta(hours=6)
_yahoo_rate_limited_until: datetime | None = None

ALPHA_RATE_LIMIT_WINDOW = timedelta(seconds=10)
_alpha_rate_limited_until: datetime | None = None
ALPHA_RETRY_DELAY_SECONDS = 10
ALPHA_RETRY_MAX_ATTEMPTS = 3

RETRY_IMMEDIATE_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 10
RETRY_MAX_ATTEMPTS = 8
RETRY_MAX_BACKOFF_SECONDS = 24 * 60 * 60


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


def _schedule_retry(
    session,
    job: DataSyncJob,
    reason: str,
    min_delay: int | None = None,
    status: str = "queued",
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
    job.status = status
    job.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
    job.message = f"{reason}; retry_in={delay}s"
    session.commit()
    record_audit(
        session,
        action="data.sync.retry",
        resource_type="data_sync_job",
        resource_id=job.id,
        detail={"dataset_id": job.dataset_id, "retry_in": delay, "reason": reason},
    )

    def _runner():
        time.sleep(delay)
        run_data_sync(job.id)

    threading.Thread(target=_runner, daemon=True).start()
    return True


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

    background_tasks.add_task(run_data_sync, job.id)
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
            background_tasks.add_task(run_data_sync, job.id)
            jobs.append(job)
            record_audit(
                session,
                action="data.sync.create",
                resource_type="data_sync_job",
                resource_id=job.id,
                detail={"dataset_id": dataset.id, "source_path": job.source_path},
            )
        session.commit()
    return jobs


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
    api_key = (settings.alpha_vantage_api_key or "").strip()
    if not api_key:
        raise RuntimeError("ALPHA_KEY_MISSING")
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
        global _alpha_rate_limited_until
        if _alpha_rate_limited_until and datetime.utcnow() < _alpha_rate_limited_until:
            raise RuntimeError("ALPHA_RATE_LIMIT")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _alpha_rate_limited_until = datetime.utcnow() + ALPHA_RATE_LIMIT_WINDOW
            raise RuntimeError("ALPHA_RATE_LIMIT") from exc
        raise RuntimeError(f"Alpha Vantage 请求失败: {exc}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Alpha Vantage 请求失败: {exc}") from exc

    if not data:
        raise RuntimeError("Alpha Vantage 返回空数据")
    if data.lstrip().startswith(b"{"):
        payload = json.loads(data.decode("utf-8", errors="ignore"))
        note = payload.get("Note") or payload.get("Information")
        error_msg = payload.get("Error Message") or payload.get("error")
        note_text = str(note or "").lower()
        if "premium" in note_text:
            raise RuntimeError("ALPHA_PREMIUM")
        if note:
            _alpha_rate_limited_until = datetime.utcnow() + ALPHA_RATE_LIMIT_WINDOW
            raise RuntimeError("ALPHA_RATE_LIMIT")
        if error_msg:
            raise RuntimeError("ALPHA_NOT_FOUND")
        raise RuntimeError("Alpha Vantage 返回异常响应")

    header = data.splitlines()[0].decode("utf-8", errors="ignore").lower()
    if "timestamp" not in header:
        raise RuntimeError("Alpha Vantage 返回缺少时间列")

    target_path.write_bytes(data)
    return target_path


def _fetch_alpha_csv_with_retry(
    symbol: str,
    dataset_id: int,
    dataset_name: str,
    outputsize: str = "full",
) -> Path:
    last_error: Exception | None = None
    for attempt in range(1, ALPHA_RETRY_MAX_ATTEMPTS + 1):
        try:
            return _fetch_alpha_csv(symbol, dataset_id, dataset_name, outputsize=outputsize)
        except RuntimeError as exc:
            last_error = exc
            if str(exc) != "ALPHA_RATE_LIMIT" or attempt >= ALPHA_RETRY_MAX_ATTEMPTS:
                raise
            time.sleep(ALPHA_RETRY_DELAY_SECONDS)
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


def run_data_sync(job_id: int) -> None:
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
        session.commit()

        dataset = session.get(Dataset, job.dataset_id)
        dataset_name = dataset.name if dataset else f"dataset_{job.dataset_id}"
        output_name = f"{job.dataset_id}_{_safe_name(dataset_name)}.csv"
        normalized_path = _get_data_root() / "normalized" / output_name
        curated_path = _get_data_root() / "curated" / output_name
        adjusted_path = _get_data_root() / "curated_adjusted" / output_name

        source_path = job.source_path
        source_label = source_path
        issues: list[str] = []
        symbol_override: str | None = None
        reset_history = bool(job.reset_history)
        factor_source: str | None = None
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
                if factor_source == "yahoo":
                    message_parts.append("factor=yahoo")
                elif factor_source == "lean":
                    message_parts.append("factor=ok")
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
            try:
                path = _fetch_alpha_csv_with_retry(alpha_symbol, job.dataset_id, dataset_name)
            except RuntimeError as exc:
                code = str(exc)
                if code == "ALPHA_RATE_LIMIT":
                    _schedule_retry(
                        session,
                        job,
                        reason="ALPHA_RATE_LIMIT",
                        min_delay=int(ALPHA_RATE_LIMIT_WINDOW.total_seconds()),
                        status="rate_limited",
                    )
                    return
                elif code == "ALPHA_NOT_FOUND":
                    job.status = "not_found"
                    job.message = "Alpha Vantage 未覆盖该代码"
                elif code == "ALPHA_PREMIUM":
                    job.status = "failed"
                    job.message = "Alpha Vantage 需要付费套餐"
                elif code == "ALPHA_KEY_MISSING":
                    job.status = "failed"
                    job.message = "Alpha Vantage API Key 未配置"
                else:
                    _schedule_retry(
                        session,
                        job,
                        reason=code,
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
        if _is_alpha_source(source_path):
            factors = _build_factors_from_alpha_csv(path)
            if factors:
                factor_source = "alpha"
                _write_factor_file(_factor_cache_path(canonical_symbol), factors)
        if not factors:
            factors = _load_factor_file(factor_path)
            if factors:
                factor_source = "lean"
        if not factors:
            factors = _build_factors_from_yahoo(canonical_symbol, dataset)
            if factors:
                factor_source = "yahoo"
                _write_factor_file(_factor_cache_path(canonical_symbol), factors)

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
        if map_path:
            message_parts.append(f"map=ok({map_path.name})")
        else:
            message_parts.append("map=missing")
        if factor_source == "yahoo":
            message_parts.append("factor=yahoo")
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
