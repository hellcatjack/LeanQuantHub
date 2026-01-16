from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal
from app.models import IBContractCache, IBHistoryJob
from app.services.ib_market import (
    _ib_data_root,
    _normalize_symbol,
    ib_adapter,
    ib_request_lock,
    write_bars_csv,
)
from app.services.ib_settings import get_or_create_ib_settings
from app.services.job_lock import JobLock
from app.services.project_symbols import collect_active_project_symbols


def _job_dir(job_id: int) -> Path:
    path = Path(settings.artifact_root) / f"ib_history_job_{job_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _progress_path(job_id: int) -> Path:
    return _job_dir(job_id) / "progress.json"


def _cancel_flag_path(job_id: int) -> Path:
    return _job_dir(job_id) / "cancel.flag"


def _write_progress(job_id: int, payload: dict) -> None:
    path = _progress_path(job_id)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def run_ib_history_job(job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(IBHistoryJob, job_id)
        if not job:
            return
        if job.status not in {"queued", "running"}:
            return
        lock = JobLock("ib_history", settings.data_root and Path(settings.data_root))
        if not lock.acquire():
            job.status = "blocked"
            job.message = "ib_history_lock_busy"
            session.commit()
            return
        try:
            log_dir = _job_dir(job_id)
            log_path = log_dir / "job.log"
            job.log_path = str(log_path)
            job.status = "running"
            job.started_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            session.commit()

            params = job.params or {}
            symbols = [
                _normalize_symbol(item)
                for item in (params.get("symbols") or [])
                if _normalize_symbol(item)
            ]
            use_project_symbols = bool(params.get("use_project_symbols"))
            if use_project_symbols or not symbols:
                symbols, _benchmarks = collect_active_project_symbols(session)
            symbols = [_normalize_symbol(item) for item in symbols if _normalize_symbol(item)]
            if not symbols:
                job.status = "failed"
                job.message = "symbols_empty"
                job.ended_at = datetime.utcnow()
                session.commit()
                return

            duration = str(params.get("duration") or "30 D")
            bar_size = str(params.get("bar_size") or "1 day")
            use_rth = bool(params.get("use_rth", True))
            store = bool(params.get("store", True))
            min_delay_seconds = float(params.get("min_delay_seconds") or 0.0)

            total = len(symbols)
            processed = 0
            success = 0
            failed = 0
            job.total_symbols = total
            job.processed_symbols = processed
            job.success_symbols = success
            job.failed_symbols = failed
            session.commit()

            settings_row = get_or_create_ib_settings(session)
            progress_last = time.monotonic()

            with ib_request_lock():
                with ib_adapter(settings_row, timeout=10.0) as api:
                    for symbol in symbols:
                        if _cancel_flag_path(job_id).exists():
                            job.status = "cancelled"
                            job.message = "cancelled"
                            break
                        session.refresh(job)
                        if job.status == "cancelled":
                            break
                        cache = (
                            session.query(IBContractCache)
                            .filter(
                                IBContractCache.symbol == symbol,
                                IBContractCache.sec_type == "STK",
                                IBContractCache.exchange == "SMART",
                                IBContractCache.currency == "USD",
                            )
                            .one_or_none()
                        )
                        exchange = cache.exchange if cache else "SMART"
                        currency = cache.currency if cache else "USD"
                        primary_exchange = cache.primary_exchange if cache else None
                        con_id = cache.con_id if cache else None
                        bars, error = api.request_historical_data(
                            symbol,
                            end_datetime=None,
                            duration=duration,
                            bar_size=bar_size,
                            use_rth=use_rth,
                            exchange=exchange,
                            currency=currency,
                            primary_exchange=primary_exchange,
                            con_id=con_id,
                        )
                        processed += 1
                        if error or not bars:
                            failed += 1
                            job.message = error or "no_history_data"
                            _append_log(log_path, f"{symbol}\tERROR\t{job.message}")
                        else:
                            success += 1
                            if store:
                                data_root = _ib_data_root() / "bars"
                                path = data_root / f"{symbol}.csv"
                                write_bars_csv(path, bars)
                            _append_log(log_path, f"{symbol}\tOK\tbars={len(bars)}")
                        job.processed_symbols = processed
                        job.success_symbols = success
                        job.failed_symbols = failed
                        job.updated_at = datetime.utcnow()
                        session.commit()
                        now = time.monotonic()
                        if now - progress_last >= 1.0:
                            _write_progress(
                                job_id,
                                {
                                    "status": job.status,
                                    "total": total,
                                    "processed": processed,
                                    "success": success,
                                    "failed": failed,
                                    "last_symbol": symbol,
                                },
                            )
                            progress_last = now
                        if min_delay_seconds > 0:
                            time.sleep(min_delay_seconds)

            if job.status != "cancelled":
                if success == 0:
                    job.status = "failed"
                elif failed > 0:
                    job.status = "partial"
                else:
                    job.status = "done"
            job.ended_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            session.commit()
            _write_progress(
                job_id,
                {
                    "status": job.status,
                    "total": total,
                    "processed": processed,
                    "success": success,
                    "failed": failed,
                    "ended_at": job.ended_at.isoformat(timespec="seconds"),
                },
            )
        finally:
            lock.release()
    finally:
        session.close()


def cancel_ib_history_job(job_id: int) -> Path:
    path = _cancel_flag_path(job_id)
    path.write_text("cancel", encoding="utf-8")
    return path
