from __future__ import annotations

import csv
import math
import re
import shutil
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import SessionLocal, get_session
from app.models import DataSyncJob, Dataset
from app.core.config import settings
from app.schemas import (
    DataSyncCreate,
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
    DatasetUpdate,
)
from app.services.audit_log import record_audit

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

MAX_PAGE_SIZE = 200
ACTIVE_SYNC_STATUSES = {"queued", "running"}


def _coerce_pagination(page: int, page_size: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


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
        stored_source = source_path
        if _is_stooq_source(source_path):
            stored_source = f"stooq:{_stooq_symbol(source_path, dataset)}"
        else:
            path = _resolve_path(source_path)
            data_root = _get_data_root()
            if not str(path).startswith(str(data_root)):
                raise HTTPException(status_code=400, detail="文件路径不在允许范围内")
            if not path.exists():
                raise HTTPException(status_code=404, detail="文件路径不存在")
            stored_source = str(path)

        existing = (
            session.query(DataSyncJob)
            .filter(
                DataSyncJob.dataset_id == dataset_id,
                DataSyncJob.source_path == stored_source,
                DataSyncJob.date_column == date_column,
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
def sync_all(background_tasks: BackgroundTasks):
    jobs: list[DataSyncOut] = []
    with get_session() as session:
        datasets = session.query(Dataset).order_by(Dataset.updated_at.desc()).all()
        for dataset in datasets:
            if not dataset.source_path:
                continue
            source_path = dataset.source_path
            stored_source = source_path
            if _is_stooq_source(source_path):
                stored_source = f"stooq:{_stooq_symbol(source_path, dataset)}"
            else:
                path = _resolve_path(source_path)
                data_root = _get_data_root()
                if not str(path).startswith(str(data_root)) or not path.exists():
                    continue
                stored_source = str(path)
            active = (
                session.query(DataSyncJob)
                .filter(
                    DataSyncJob.dataset_id == dataset.id,
                    DataSyncJob.source_path == stored_source,
                    DataSyncJob.date_column == "date",
                    DataSyncJob.status.in_(ACTIVE_SYNC_STATUSES),
                )
                .first()
            )
            if active:
                continue
            job = DataSyncJob(
                dataset_id=dataset.id,
                source_path=stored_source,
                date_column="date",
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
    return lowered.startswith("stooq:") or lowered.startswith("stooq://")


def _normalize_symbol(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\.]", "", value.strip())
    return cleaned or "UNKNOWN"


def _stooq_symbol(source_path: str, dataset: Dataset | None) -> str:
    raw = source_path.strip()
    if raw.lower().startswith("stooq://"):
        raw = raw[8:]
    elif raw.lower().startswith("stooq:"):
        raw = raw[6:]
    symbol = _normalize_symbol(raw or (dataset.name if dataset else ""))
    symbol = symbol.lower()
    if "." not in symbol:
        region = (dataset.region or "").strip().lower() if dataset else ""
        suffix = "hk" if region in {"hk", "hongkong"} else "us"
        symbol = f"{symbol}.{suffix}"
    return symbol


def _fetch_stooq_csv(symbol: str, dataset_id: int, dataset_name: str) -> Path:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    target_dir = _get_data_root() / "raw" / "stooq"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{dataset_id}_{_safe_name(dataset_name)}.csv"
    target_path = target_dir / filename
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"Stooq 请求失败: {response.status}")
            data = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Stooq 请求失败: {exc}") from exc
    if not data or b"Date" not in data:
        raise RuntimeError("Stooq 返回空数据")
    target_path.write_bytes(data)
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
            raw_factor = row[1].strip()
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
        reset_history = False
        if _is_stooq_source(source_path):
            stooq_symbol = _stooq_symbol(source_path, dataset)
            path = _fetch_stooq_csv(stooq_symbol, job.dataset_id, dataset_name)
            source_label = f"stooq:{stooq_symbol}"
            base_symbol = stooq_symbol.split(".", 1)[0] if "." in stooq_symbol else stooq_symbol
            symbol_override = base_symbol.upper()
            reset_history = True
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
        factor_path = (
            lean_root / "equity" / "usa" / "factor_files" / f"{canonical_symbol.lower()}.csv"
        )
        factors = _load_factor_file(factor_path)

        source_files = _collect_csv_files(path)
        records, raw_rows, _, _, issues = _normalize_records(
            source_files, job.date_column, dataset_name, symbol_override
        )
        if not records:
            raise RuntimeError("未找到可用记录")

        if reset_history:
            normalized_path.unlink(missing_ok=True)
        last_norm_dt = _get_last_date(normalized_path)
        norm_records = [
            record for record in records if last_norm_dt is None or record[0] > last_norm_dt
        ]
        _append_normalized(normalized_path, [row for _, row in norm_records])

        last_cur_dt = _get_last_date(curated_path)
        if reset_history:
            last_cur_dt = None
        curated_records = _load_curated(curated_path)
        for timestamp, row in records:
            if last_cur_dt is not None and timestamp < last_cur_dt:
                continue
            existing = curated_records.get(timestamp)
            if existing is None or _row_score(row) >= _row_score(existing):
                curated_records[timestamp] = row
        _write_curated(curated_path, curated_records)
        adjusted_records = _apply_price_factors(curated_records, factors)
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
        if factors:
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

    vendor = (payload.vendor or "stooq").strip().lower()
    if vendor != "stooq":
        raise HTTPException(status_code=400, detail="当前仅支持 Stooq 数据源")

    frequency = (payload.frequency or "daily").strip().lower()
    if frequency not in {"daily", "minute"}:
        raise HTTPException(status_code=400, detail="不支持的频率")
    if vendor == "stooq" and frequency != "daily":
        raise HTTPException(status_code=400, detail="Stooq 仅支持日线数据")

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
            DataSyncCreate(source_path=source_path, date_column="date"),
            background_tasks,
        )
        job_out = DataSyncOut.model_validate(job, from_attributes=True)

    return DatasetFetchOut(
        dataset=DatasetOut.model_validate(dataset, from_attributes=True),
        job=job_out,
        created=created,
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
