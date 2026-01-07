from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import SessionLocal
from app.models import PitFundamentalJob, PitWeeklyJob
from app.services.audit_log import record_audit


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

    return cmd


def _build_fundamental_fetch_command(
    params: dict[str, Any], progress_path: Path | None = None
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

    refresh_days = int(params.get("refresh_days") or 30)
    cmd.extend(["--refresh-days", str(refresh_days)])

    min_delay = float(params.get("min_delay_seconds") or 0.8)
    cmd.extend(["--min-delay", str(min_delay)])

    max_retries = int(params.get("max_retries") or 3)
    cmd.extend(["--max-retries", str(max_retries)])

    rate_limit_sleep = float(params.get("rate_limit_sleep") or 60.0)
    cmd.extend(["--rate-limit-sleep", str(rate_limit_sleep)])
    rate_limit_retries = int(params.get("rate_limit_retries") or 3)
    cmd.extend(["--rate-limit-retries", str(rate_limit_retries)])

    if progress_path:
        cmd.extend(["--progress-path", str(progress_path)])

    return cmd


def run_pit_weekly_job(job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(PitWeeklyJob, job_id)
        if not job:
            return
        if job.status == "running":
            return

        params = dict(job.params or {})
        output_dir = _resolve_output_dir(params)
        log_dir = Path(settings.artifact_root) / f"pit_weekly_job_{job_id}"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "run.log"
        progress_path = log_dir / "progress.json"
        calendar_path = log_dir / "calendar.json"

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.output_dir = output_dir
        job.log_path = str(log_path)
        session.commit()

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
            "rebalance_mode": str(params.get("rebalance_mode") or "week_open").strip().lower(),
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
            validate_cmd = _build_weekly_validate_command(params, output_dir, quality_path)
            validate_proc = subprocess.run(
                validate_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False
            )

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
        if job.status == "running":
            return

        params = dict(job.params or {})
        output_dir = _resolve_fundamental_output_dir(params)
        log_dir = Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "run.log"
        progress_path = log_dir / "progress.json"

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.output_dir = output_dir
        job.log_path = str(log_path)
        session.commit()

        _write_progress(
            progress_path,
            {"stage": "fetch", "status": "running", "updated_at": datetime.utcnow().isoformat()},
        )

        with log_path.open("w", encoding="utf-8") as handle:
            if params.get("refresh_fundamentals"):
                fetch_cmd = _build_fundamental_fetch_command(params, progress_path)
                handle.write("[fetch]\n")
                handle.flush()
                fetch_proc = subprocess.run(
                    fetch_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False
                )
                if fetch_proc.returncode != 0:
                    raise RuntimeError(f"fundamentals_fetch_failed={fetch_proc.returncode}")

            _write_progress(
                progress_path,
                {"stage": "build", "status": "running", "updated_at": datetime.utcnow().isoformat()},
            )
            build_cmd = _build_fundamental_command(params, output_dir)
            handle.write("[build]\n")
            handle.flush()
            proc = subprocess.run(build_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)

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
