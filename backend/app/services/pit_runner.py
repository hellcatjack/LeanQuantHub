from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import SessionLocal
from app.models import PitFundamentalJob, PitWeeklyJob
from app.services.audit_log import record_audit
from app.services.alpha_rate import alpha_rate_config_path, write_alpha_rate_config
from app.services.job_lock import JobLock


FUNDAMENTAL_CANCEL_EXIT_CODE = 130


class _PitFundamentalCanceled(RuntimeError):
    pass


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_output_dir(params: dict[str, Any]) -> str | None:
    data_root = str(params.get("data_root") or "").strip()
    output_dir = str(params.get("output_dir") or "").strip()
    if output_dir:
        return output_dir
    if data_root:
        return str(Path(data_root) / "universe" / "pit_weekly")
    if settings.data_root:
        return str(Path(settings.data_root) / "universe" / "pit_weekly")
    return None


def _build_command(params: dict[str, Any], output_dir: str | None) -> list[str]:
    script_path = _project_root() / "scripts" / "build_pit_weekly_snapshots.py"
    cmd = [sys.executable, str(script_path)]

    data_root = str(params.get("data_root") or settings.data_root or "").strip()
    if data_root:
        cmd.extend(["--data-root", data_root])
    if output_dir:
        cmd.extend(["--output-dir", output_dir])

    symbol_life = str(params.get("symbol_life") or "").strip()
    if symbol_life:
        cmd.extend(["--symbol-life", symbol_life])
    start = str(params.get("start") or "").strip()
    if start:
        cmd.extend(["--start", start])
    end = str(params.get("end") or "").strip()
    if end:
        cmd.extend(["--end", end])

    rebalance_mode = str(params.get("rebalance_mode") or "week_open").strip()
    rebalance_day = str(params.get("rebalance_day") or "monday").strip()
    cmd.extend(["--rebalance-mode", rebalance_mode, "--rebalance-day", rebalance_day])

    benchmark = str(params.get("benchmark") or "SPY").strip()
    cmd.extend(["--benchmark", benchmark])
    market_timezone = str(params.get("market_timezone") or settings.market_timezone or "").strip()
    if market_timezone:
        cmd.extend(["--market-timezone", market_timezone])
    market_session_open = str(
        params.get("market_session_open") or settings.market_session_open or ""
    ).strip()
    if market_session_open:
        cmd.extend(["--session-open", market_session_open])
    market_session_close = str(
        params.get("market_session_close") or settings.market_session_close or ""
    ).strip()
    if market_session_close:
        cmd.extend(["--session-close", market_session_close])
    asset_type = str(params.get("asset_type") or "Stock").strip()
    cmd.extend(["--asset-type", asset_type])

    if params.get("require_data"):
        cmd.append("--require-data")

    vendor_preference = str(params.get("vendor_preference") or "").strip()
    if vendor_preference:
        cmd.extend(["--vendor-preference", vendor_preference])

    return cmd


def _build_weekly_validate_command(
    params: dict[str, Any], output_dir: str | None, summary_path: Path | None
) -> list[str]:
    script_path = _project_root() / "scripts" / "validate_pit_weekly_snapshots.py"
    cmd = [sys.executable, str(script_path)]

    data_root = str(params.get("data_root") or settings.data_root or "").strip()
    if data_root:
        cmd.extend(["--data-root", data_root])
    if output_dir:
        cmd.extend(["--pit-dir", output_dir])

    symbol_life = str(params.get("symbol_life") or "").strip()
    if symbol_life:
        cmd.extend(["--symbol-life", symbol_life])
    symbol_map = str(params.get("symbol_map_path") or "").strip()
    if not symbol_map:
        data_root = str(params.get("data_root") or settings.data_root or "").strip()
        if data_root:
            candidate = Path(data_root) / "universe" / "symbol_map.csv"
            if candidate.exists():
                symbol_map = str(candidate)
    if symbol_map:
        cmd.extend(["--symbol-map", symbol_map])

    benchmark = str(params.get("benchmark") or "SPY").strip()
    cmd.extend(["--benchmark", benchmark])
    asset_type = str(params.get("asset_type") or "Stock").strip()
    cmd.extend(["--asset-type", asset_type])

    vendor_preference = str(params.get("vendor_preference") or "").strip()
    if vendor_preference:
        cmd.extend(["--vendor-preference", vendor_preference])

    if params.get("require_data"):
        cmd.append("--require-data")

    cmd.append("--fix")

    if summary_path:
        cmd.extend(["--summary-path", str(summary_path)])

    return cmd


def _parse_log_summary(log_path: Path) -> tuple[int | None, str | None]:
    if not log_path.exists():
        return None, None
    snapshot_count = None
    last_snapshot = None
    content = log_path.read_text(encoding="utf-8", errors="ignore")
    for line in content.splitlines():
        if line.startswith("snapshot: "):
            last_snapshot = line.split("snapshot: ", 1)[1].split(" symbols=", 1)[0].strip()
        elif line.startswith("total snapshots:"):
            value = line.split(":", 1)[1].strip()
            if value.isdigit():
                snapshot_count = int(value)
    return snapshot_count, last_snapshot


def _write_progress(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _resolve_fundamental_output_dir(params: dict[str, Any]) -> str | None:
    output_dir = str(params.get("output_dir") or "").strip()
    if output_dir:
        return output_dir
    data_root = str(params.get("data_root") or "").strip()
    if data_root:
        return str(Path(data_root) / "factors" / "pit_weekly_fundamentals")
    if settings.data_root:
        return str(Path(settings.data_root) / "factors" / "pit_weekly_fundamentals")
    return None


def _build_fundamental_command(params: dict[str, Any], output_dir: str | None) -> list[str]:
    script_path = _project_root() / "scripts" / "build_pit_fundamentals_snapshots.py"
    cmd = [sys.executable, str(script_path)]

    data_root = str(params.get("data_root") or settings.data_root or "").strip()
    if data_root:
        cmd.extend(["--data-root", data_root])
    if output_dir:
        cmd.extend(["--output-dir", output_dir])

    pit_dir = str(params.get("pit_dir") or "").strip()
    if pit_dir:
        cmd.extend(["--pit-dir", pit_dir])
    fundamentals_dir = str(params.get("fundamentals_dir") or "").strip()
    if fundamentals_dir:
        cmd.extend(["--fundamentals-dir", fundamentals_dir])

    start = str(params.get("start") or "").strip()
    if start:
        cmd.extend(["--start", start])
    end = str(params.get("end") or "").strip()
    if end:
        cmd.extend(["--end", end])

    report_delay_days = int(params.get("report_delay_days") or 1)
    cmd.extend(["--report-delay-days", str(report_delay_days)])
    missing_report_delay_days = int(params.get("missing_report_delay_days") or 45)
    cmd.extend(["--missing-report-delay-days", str(missing_report_delay_days)])
    shares_delay_days = int(params.get("shares_delay_days") or 45)
    cmd.extend(["--shares-delay-days", str(shares_delay_days)])
    shares_preference = str(params.get("shares_preference") or "diluted").strip()
    cmd.extend(["--shares-preference", shares_preference])
    price_source = str(params.get("price_source") or "raw").strip()
    cmd.extend(["--price-source", price_source])

    benchmark = str(params.get("benchmark") or "SPY").strip()
    cmd.extend(["--benchmark", benchmark])
    vendor_preference = str(params.get("vendor_preference") or "").strip()
    if vendor_preference:
        cmd.extend(["--vendor-preference", vendor_preference])

    exclude_symbols_path = str(params.get("exclude_symbols_path") or "").strip()
    if not exclude_symbols_path and data_root:
        long_term_exclude = Path(data_root) / "universe" / "fundamentals_exclude.csv"
        if long_term_exclude.exists():
            exclude_symbols_path = str(long_term_exclude)
        else:
            default_exclude = Path(data_root) / "universe" / "fundamentals_missing.csv"
            if default_exclude.exists():
                exclude_symbols_path = str(default_exclude)
    if exclude_symbols_path:
        cmd.extend(["--exclude-symbols", exclude_symbols_path])
    asset_types = str(params.get("asset_types") or "").strip()
    if asset_types:
        cmd.extend(["--asset-types", asset_types])

    return cmd


def _build_fundamental_fetch_command(
    params: dict[str, Any],
    progress_path: Path | None = None,
    status_path: Path | None = None,
    resume_path: Path | None = None,
    cancel_path: Path | None = None,
    skip_lock: bool = False,
) -> list[str]:
    script_path = _project_root() / "scripts" / "fetch_alpha_fundamentals.py"
    cmd = [sys.executable, str(script_path), "--from-pit"]

    data_root = str(params.get("data_root") or settings.data_root or "").strip()
    if data_root:
        cmd.extend(["--data-root", data_root])

    pit_dir = str(params.get("pit_dir") or "").strip()
    if pit_dir:
        cmd.extend(["--pit-dir", pit_dir])

    start = str(params.get("start") or "").strip()
    if start:
        cmd.extend(["--start", start])
    end = str(params.get("end") or "").strip()
    if end:
        cmd.extend(["--end", end])

    refresh_days_raw = params.get("refresh_days")
    if refresh_days_raw is None:
        refresh_days = 0
    else:
        try:
            refresh_days = int(refresh_days_raw)
        except (TypeError, ValueError):
            refresh_days = 0
    cmd.extend(["--refresh-days", str(refresh_days)])

    min_delay = float(params.get("min_delay_seconds") or 0.45)
    cmd.extend(["--min-delay", str(min_delay)])

    max_retries = int(params.get("max_retries") or 3)
    cmd.extend(["--max-retries", str(max_retries)])

    rate_limit_sleep = float(params.get("rate_limit_sleep") or 10.0)
    cmd.extend(["--rate-limit-sleep", str(rate_limit_sleep)])
    rate_limit_retries = int(params.get("rate_limit_retries") or 3)
    cmd.extend(["--rate-limit-retries", str(rate_limit_retries)])

    if progress_path:
        cmd.extend(["--progress-path", str(progress_path)])
    if status_path:
        cmd.extend(["--status-path", str(status_path)])
    if cancel_path:
        cmd.extend(["--cancel-path", str(cancel_path)])

    if data_root:
        rate_config = alpha_rate_config_path(Path(data_root))
        cmd.extend(["--rate-config", str(rate_config)])
    if resume_path or params.get("resume_fundamentals"):
        cmd.append("--resume")
    if resume_path:
        cmd.extend(["--resume-path", str(resume_path)])
    if skip_lock:
        cmd.append("--skip-lock")

    return cmd


def _resolve_data_root(params: dict[str, Any]) -> Path | None:
    data_root = str(params.get("data_root") or settings.data_root or "").strip()
    if not data_root:
        return None
    return Path(data_root).expanduser().resolve()


def _resolve_pit_dir(params: dict[str, Any], data_root: Path | None) -> Path | None:
    pit_dir = str(params.get("pit_dir") or "").strip()
    if pit_dir:
        path = Path(pit_dir)
        if not path.is_absolute() and data_root:
            path = data_root / path
        return path
    if data_root:
        return data_root / "universe" / "pit_weekly"
    return None


def _resolve_fundamentals_root(params: dict[str, Any], data_root: Path | None) -> Path | None:
    fundamentals_dir = str(params.get("fundamentals_dir") or "").strip()
    if fundamentals_dir:
        path = Path(fundamentals_dir)
        if not path.is_absolute() and data_root:
            path = data_root / path
        return path
    if data_root:
        return data_root / "fundamentals" / "alpha"
    return None


def _parse_date_value(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_snapshot_date(path: Path) -> date | None:
    stem = path.stem
    if not stem.startswith("pit_"):
        return None
    return _parse_date_value(stem.split("_", 1)[1])


def _collect_pit_symbols(
    pit_dir: Path | None, start: date | None, end: date | None
) -> list[str]:
    if not pit_dir or not pit_dir.exists():
        return []
    symbols: set[str] = set()
    for path in pit_dir.glob("pit_*.csv"):
        snapshot_date = _parse_snapshot_date(path)
        if start and snapshot_date and snapshot_date < start:
            continue
        if end and snapshot_date and snapshot_date > end:
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    symbol = (row.get("symbol") or "").strip().upper()
                    if symbol:
                        symbols.add(symbol)
        except OSError:
            continue
    return sorted(symbols)


FUNDAMENTAL_FILES = (
    "overview.json",
    "income_statement.json",
    "balance_sheet.json",
    "cash_flow.json",
    "earnings.json",
)


def _collect_missing_fundamentals(
    fundamentals_root: Path | None, symbols: list[str]
) -> list[dict[str, str]]:
    if not fundamentals_root:
        return [{"symbol": symbol, "reason": "missing_root"} for symbol in symbols]
    missing: list[dict[str, str]] = []
    for symbol in symbols:
        symbol_dir = fundamentals_root / symbol
        if not symbol_dir.exists():
            missing.append({"symbol": symbol, "reason": "missing_dir"})
            continue
        missing_files = [
            filename for filename in FUNDAMENTAL_FILES if not (symbol_dir / filename).exists()
        ]
        if missing_files:
            missing.append(
                {"symbol": symbol, "reason": f"missing_files:{','.join(missing_files)}"}
            )
    return missing


def _write_missing_fundamentals(path: Path, missing: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "reason"])
        writer.writeheader()
        for row in missing:
            writer.writerow({"symbol": row.get("symbol", ""), "reason": row.get("reason", "")})
    tmp_path.replace(path)


def _build_fundamental_missing_fetch_command(
    params: dict[str, Any],
    symbol_file: Path,
    progress_path: Path | None = None,
    cancel_path: Path | None = None,
) -> list[str]:
    script_path = _project_root() / "scripts" / "fetch_alpha_fundamentals.py"
    cmd = [sys.executable, str(script_path), "--symbol-file", str(symbol_file)]

    data_root = str(params.get("data_root") or settings.data_root or "").strip()
    if data_root:
        cmd.extend(["--data-root", data_root])

    refresh_days_raw = params.get("refresh_days")
    if refresh_days_raw is None:
        refresh_days = 0
    else:
        try:
            refresh_days = int(refresh_days_raw)
        except (TypeError, ValueError):
            refresh_days = 0
    cmd.extend(["--refresh-days", str(refresh_days)])

    min_delay = float(params.get("min_delay_seconds") or 0.45)
    cmd.extend(["--min-delay", str(min_delay)])

    max_retries = int(params.get("max_retries") or 3)
    cmd.extend(["--max-retries", str(max_retries)])

    rate_limit_sleep = float(params.get("rate_limit_sleep") or 10.0)
    cmd.extend(["--rate-limit-sleep", str(rate_limit_sleep)])
    rate_limit_retries = int(params.get("rate_limit_retries") or 3)
    cmd.extend(["--rate-limit-retries", str(rate_limit_retries)])

    if progress_path:
        cmd.extend(["--progress-path", str(progress_path)])
    if cancel_path:
        cmd.extend(["--cancel-path", str(cancel_path)])

    if data_root:
        rate_config = alpha_rate_config_path(Path(data_root))
        cmd.extend(["--rate-config", str(rate_config)])
    cmd.append("--skip-lock")

    return cmd


def run_pit_weekly_job(job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(PitWeeklyJob, job_id)
        if not job:
            return
        if job.status in {"running", "canceled"}:
            return
        if job.status == "cancel_requested":
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            log_dir = Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}"
            progress_path = log_dir / "progress.json"
            _write_progress(
                progress_path,
                {
                    "stage": "canceled",
                    "status": "canceled",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            session.commit()
            return

        params = dict(job.params or {})
        log_dir = Path(settings.artifact_root) / f"pit_weekly_job_{job_id}"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "run.log"
        progress_path = log_dir / "progress.json"
        calendar_path = log_dir / "calendar.json"
        data_root = str(params.get("data_root") or settings.data_root or "").strip()
        data_root_path = _resolve_data_root(params)
        lock_root = data_root_path if data_root_path else None
        pit_lock = JobLock("pit_weekly", lock_root)
        if not pit_lock.acquire():
            job.status = "blocked"
            job.message = "pit_weekly_lock_busy"
            job.ended_at = datetime.utcnow()
            _write_progress(
                progress_path,
                {
                    "stage": "failed",
                    "status": "failed",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_weekly_job.blocked",
                resource_type="pit_weekly_job",
                resource_id=job_id,
                detail={"error": job.message},
            )
            session.commit()
            return

        output_dir = _resolve_output_dir(params)

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.output_dir = output_dir
        job.log_path = str(log_path)
        session.commit()

        try:
            _write_progress(
                progress_path,
                {
                    "stage": "build",
                    "status": "running",
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            cmd = _build_command(params, output_dir)
            calendar_payload = {
                "calendar_symbol": str(params.get("benchmark") or "SPY").strip(),
                "market_timezone": str(
                    params.get("market_timezone") or settings.market_timezone or ""
                ).strip(),
                "market_session_open": str(
                    params.get("market_session_open") or settings.market_session_open or ""
                ).strip(),
                "market_session_close": str(
                    params.get("market_session_close") or settings.market_session_close or ""
                ).strip(),
                "rebalance_mode": str(params.get("rebalance_mode") or "week_open")
                .strip()
                .lower(),
                "rebalance_day": str(params.get("rebalance_day") or "monday").strip().lower(),
                "snapshot_rule": "previous_trading_close",
            }
            calendar_path.write_text(
                json.dumps(calendar_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            quality_path = log_dir / "quality.json"
            with log_path.open("w", encoding="utf-8") as handle:
                proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
                handle.write("[quality]\n")
                handle.flush()
                _write_progress(
                    progress_path,
                    {
                        "stage": "validate",
                        "status": "running",
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
                validate_cmd = _build_weekly_validate_command(params, output_dir, quality_path)
                validate_proc = subprocess.run(
                    validate_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False
                )
        finally:
            pit_lock.release()

        snapshot_count, last_snapshot = _parse_log_summary(log_path)
        job = session.get(PitWeeklyJob, job_id)
        if not job:
            return
        job.snapshot_count = snapshot_count
        job.last_snapshot_path = last_snapshot
        job.ended_at = datetime.utcnow()
        if proc.returncode == 0 and validate_proc.returncode == 0:
            job.status = "success"
            if snapshot_count is not None:
                job.message = f"snapshots={snapshot_count}"
            else:
                job.message = "success"
            _write_progress(
                progress_path,
                {
                    "stage": "done",
                    "status": "success",
                    "snapshot_count": snapshot_count,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_weekly_job.success",
                resource_type="pit_weekly_job",
                resource_id=job_id,
                detail={"snapshot_count": snapshot_count, "last_snapshot": last_snapshot},
            )
        else:
            job.status = "failed"
            job.message = f"exit_code={proc.returncode}; quality={validate_proc.returncode}"
            _write_progress(
                progress_path,
                {
                    "stage": "failed",
                    "status": "failed",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_weekly_job.failed",
                resource_type="pit_weekly_job",
                resource_id=job_id,
                detail={"exit_code": proc.returncode},
            )
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(PitWeeklyJob, job_id)
        if job:
            job.status = "failed"
            job.message = str(exc)
            job.ended_at = datetime.utcnow()
            _write_progress(
                Path(settings.artifact_root) / f"pit_weekly_job_{job_id}" / "progress.json",
                {
                    "stage": "failed",
                    "status": "failed",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_weekly_job.failed",
                resource_type="pit_weekly_job",
                resource_id=job_id,
                detail={"error": str(exc)},
            )
            session.commit()
    finally:
        session.close()


def run_pit_fundamental_job(job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(PitFundamentalJob, job_id)
        if not job:
            return
        if job.status in {"running", "canceled"}:
            return
        if job.status == "cancel_requested":
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            log_dir = Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}"
            progress_path = log_dir / "progress.json"
            _write_progress(
                progress_path,
                {
                    "stage": "canceled",
                    "status": "canceled",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            session.commit()
            return

        params = dict(job.params or {})
        output_dir = _resolve_fundamental_output_dir(params)
        log_dir = Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "run.log"
        progress_path = log_dir / "progress.json"
        cancel_path = log_dir / "cancel.flag"
        data_root = str(params.get("data_root") or settings.data_root or "").strip()
        data_root_path = _resolve_data_root(params)
        lock_root = data_root_path if data_root_path else None
        pit_lock = JobLock("pit_fundamental", lock_root)
        if not pit_lock.acquire():
            job.status = "blocked"
            job.message = "pit_fundamental_lock_busy"
            job.ended_at = datetime.utcnow()
            _write_progress(
                progress_path,
                {
                    "stage": "failed",
                    "status": "failed",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_fundamental_job.blocked",
                resource_type="pit_fundamental_job",
                resource_id=job_id,
                detail={"error": job.message},
            )
            session.commit()
            return

        alpha_lock: JobLock | None = None

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.output_dir = output_dir
        job.log_path = str(log_path)
        session.commit()

        _write_progress(
            progress_path,
            {"stage": "fetch", "status": "running", "updated_at": datetime.utcnow().isoformat()},
        )

        missing_count: int | None = None
        missing_path: Path | None = None
        total_symbols: int | None = None

        def check_canceled() -> None:
            if cancel_path.exists():
                raise _PitFundamentalCanceled("cancel_requested")

        try:
            with log_path.open("w", encoding="utf-8") as handle:
                check_canceled()
                if params.get("refresh_fundamentals"):
                    alpha_lock = JobLock("alpha_fetch", lock_root)
                    if not alpha_lock.acquire():
                        job = session.get(PitFundamentalJob, job_id)
                        if job:
                            job.status = "blocked"
                            job.message = "alpha_lock_busy"
                            job.ended_at = datetime.utcnow()
                            _write_progress(
                                progress_path,
                                {
                                    "stage": "failed",
                                    "status": "failed",
                                    "message": job.message,
                                    "updated_at": datetime.utcnow().isoformat(),
                                },
                            )
                            record_audit(
                                session,
                                action="pit_fundamental_job.failed",
                                resource_type="pit_fundamental_job",
                                resource_id=job_id,
                                detail={"error": job.message},
                            )
                            session.commit()
                        return
                    rate_updates = {
                        "min_delay_seconds": params.get("min_delay_seconds"),
                        "rate_limit_sleep": params.get("rate_limit_sleep"),
                        "rate_limit_retries": params.get("rate_limit_retries"),
                        "max_retries": params.get("max_retries"),
                    }
                    write_alpha_rate_config(rate_updates, lock_root)
                    status_path = log_dir / "fundamentals_status.csv"
                    resume_path: Path | None = None
                    resume_from = params.get("resume_from_job_id")
                    if resume_from:
                        resume_path = (
                            Path(settings.artifact_root)
                            / f"pit_fundamental_job_{resume_from}"
                            / "fundamentals_status.csv"
                        )
                    elif params.get("resume_fundamentals"):
                        resume_path = status_path
                    fetch_cmd = _build_fundamental_fetch_command(
                        params,
                        progress_path,
                        status_path=status_path,
                        resume_path=resume_path,
                        cancel_path=cancel_path,
                        skip_lock=True,
                    )
                    handle.write("[fetch]\n")
                    handle.flush()
                    fetch_proc = subprocess.run(
                        fetch_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False
                    )
                    if fetch_proc.returncode == FUNDAMENTAL_CANCEL_EXIT_CODE:
                        raise _PitFundamentalCanceled("fetch_canceled")
                    if fetch_proc.returncode != 0:
                        raise RuntimeError(
                            f"fundamentals_fetch_failed={fetch_proc.returncode}"
                        )

                check_canceled()
                _write_progress(
                    progress_path,
                    {
                        "stage": "build",
                        "status": "running",
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )
                build_cmd = _build_fundamental_command(params, output_dir)
                handle.write("[build]\n")
                handle.flush()
                proc = subprocess.run(
                    build_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False
                )
                if proc.returncode == 0:
                    start_date = _parse_date_value(str(params.get("start") or "").strip())
                    end_date = _parse_date_value(str(params.get("end") or "").strip())
                    pit_dir = _resolve_pit_dir(params, data_root_path)
                    fundamentals_root = _resolve_fundamentals_root(params, data_root_path)
                    symbols = _collect_pit_symbols(pit_dir, start_date, end_date)
                    total_symbols = len(symbols)
                    missing_rows = _collect_missing_fundamentals(fundamentals_root, symbols)
                    missing_count = len(missing_rows)
                    missing_path = log_dir / "missing_fundamentals.csv"
                    _write_missing_fundamentals(missing_path, missing_rows)
                    handle.write(
                        f"[coverage] total_symbols={total_symbols} missing={missing_count}\n"
                    )
                    handle.flush()
                    _write_progress(
                        progress_path,
                        {
                            "stage": "coverage",
                            "status": "running",
                            "total_symbols": total_symbols,
                            "missing_count": missing_count,
                            "missing_path": str(missing_path),
                            "updated_at": datetime.utcnow().isoformat(),
                        },
                    )
                    if params.get("refresh_fundamentals") and missing_count:
                        check_canceled()
                        _write_progress(
                            progress_path,
                            {
                                "stage": "backfill",
                                "status": "running",
                                "missing_count": missing_count,
                                "updated_at": datetime.utcnow().isoformat(),
                            },
                        )
                        backfill_cmd = _build_fundamental_missing_fetch_command(
                            params,
                            missing_path,
                            progress_path,
                            cancel_path=cancel_path,
                        )
                        handle.write("[backfill]\n")
                        handle.flush()
                        backfill_proc = subprocess.run(
                            backfill_cmd,
                            stdout=handle,
                            stderr=subprocess.STDOUT,
                            check=False,
                        )
                        if backfill_proc.returncode == FUNDAMENTAL_CANCEL_EXIT_CODE:
                            raise _PitFundamentalCanceled("backfill_canceled")
                        if backfill_proc.returncode != 0:
                            raise RuntimeError(
                                f"fundamentals_backfill_failed={backfill_proc.returncode}"
                            )
                        check_canceled()
                        _write_progress(
                            progress_path,
                            {
                                "stage": "rebuild",
                                "status": "running",
                                "updated_at": datetime.utcnow().isoformat(),
                            },
                        )
                        handle.write("[rebuild]\n")
                        handle.flush()
                        proc = subprocess.run(
                            build_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False
                        )
                        if proc.returncode != 0:
                            raise RuntimeError(
                                f"fundamentals_rebuild_failed={proc.returncode}"
                            )
                        missing_rows = _collect_missing_fundamentals(
                            fundamentals_root, symbols
                        )
                        missing_count = len(missing_rows)
                        _write_missing_fundamentals(missing_path, missing_rows)
                        _write_progress(
                            progress_path,
                            {
                                "stage": "coverage",
                                "status": "running",
                                "total_symbols": total_symbols,
                                "missing_count": missing_count,
                                "missing_path": str(missing_path),
                                "updated_at": datetime.utcnow().isoformat(),
                            },
                        )
        finally:
            if alpha_lock:
                alpha_lock.release()
            pit_lock.release()

        snapshot_count, last_snapshot = _parse_log_summary(log_path)
        job = session.get(PitFundamentalJob, job_id)
        if not job:
            return
        job.snapshot_count = snapshot_count
        job.last_snapshot_path = last_snapshot
        job.ended_at = datetime.utcnow()
        if proc.returncode == 0:
            job.status = "success"
            if snapshot_count is not None:
                if missing_count is not None:
                    job.message = f"snapshots={snapshot_count}; missing={missing_count}"
                else:
                    job.message = f"snapshots={snapshot_count}"
            else:
                job.message = "success"
            _write_progress(
                progress_path,
                {
                    "stage": "done",
                    "status": "success",
                    "snapshot_count": snapshot_count,
                    "missing_count": missing_count,
                    "missing_path": str(missing_path) if missing_path else None,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_fundamental_job.success",
                resource_type="pit_fundamental_job",
                resource_id=job_id,
                detail={"snapshot_count": snapshot_count, "last_snapshot": last_snapshot},
            )
        else:
            job.status = "failed"
            job.message = f"exit_code={proc.returncode}"
            _write_progress(
                progress_path,
                {
                    "stage": "failed",
                    "status": "failed",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_fundamental_job.failed",
                resource_type="pit_fundamental_job",
                resource_id=job_id,
                detail={"exit_code": proc.returncode},
            )
        session.commit()
    except _PitFundamentalCanceled:
        session.rollback()
        job = session.get(PitFundamentalJob, job_id)
        if job:
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            progress_path = (
                Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}" / "progress.json"
            )
            _write_progress(
                progress_path,
                {
                    "stage": "canceled",
                    "status": "canceled",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_fundamental_job.cancel",
                resource_type="pit_fundamental_job",
                resource_id=job_id,
                detail={"status": job.status},
            )
            session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(PitFundamentalJob, job_id)
        if job:
            job.status = "failed"
            job.message = str(exc)
            job.ended_at = datetime.utcnow()
            progress_path = (
                Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}" / "progress.json"
            )
            _write_progress(
                progress_path,
                {
                    "stage": "failed",
                    "status": "failed",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
            record_audit(
                session,
                action="pit_fundamental_job.failed",
                resource_type="pit_fundamental_job",
                resource_id=job_id,
                detail={"error": str(exc)},
            )
            session.commit()
    finally:
        session.close()
