from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal
from app.models import AutoWeeklyJob, PitFundamentalJob, PitWeeklyJob, ProjectVersion
from app.routes.projects import PROJECT_BACKTEST_TAG, _run_thematic_backtest_task
from app.services.audit_log import record_audit
from app.services.pit_runner import run_pit_fundamental_job, run_pit_weekly_job


def _write_log(handle, message: str) -> None:
    timestamp = datetime.utcnow().isoformat()
    handle.write(f"[{timestamp}] {message}\n")
    handle.flush()


def _latest_backtest_version(session, project_id: int) -> ProjectVersion | None:
    return (
        session.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project_id,
            ProjectVersion.description == PROJECT_BACKTEST_TAG,
        )
        .order_by(ProjectVersion.created_at.desc())
        .first()
    )


def run_auto_weekly_job(job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(AutoWeeklyJob, job_id)
        if not job:
            return
        if job.status == "running":
            return

        params = dict(job.params or {})
        log_dir = Path(settings.artifact_root) / f"auto_weekly_job_{job_id}"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "run.log"

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.log_path = str(log_path)
        session.commit()

        run_pit_weekly = bool(params.get("run_pit_weekly", True))
        run_pit_fundamentals = bool(params.get("run_pit_fundamentals", True))
        run_backtest = bool(params.get("run_backtest", True))

        with log_path.open("w", encoding="utf-8") as handle:
            _write_log(handle, f"job={job_id} project={job.project_id} start")

            if run_pit_weekly:
                pit_params = {
                    "start": params.get("pit_start"),
                    "end": params.get("pit_end"),
                    "require_data": bool(params.get("pit_require_data", False)),
                }
                vendor_pref = params.get("pit_vendor_preference")
                if vendor_pref:
                    pit_params["vendor_preference"] = str(vendor_pref)
                pit_job = PitWeeklyJob(status="queued", params=pit_params)
                session.add(pit_job)
                session.commit()
                session.refresh(pit_job)
                job.pit_weekly_job_id = pit_job.id
                session.commit()
                _write_log(handle, f"pit_weekly_job={pit_job.id} start")
                run_pit_weekly_job(pit_job.id)
                session.refresh(pit_job)
                job.pit_weekly_log_path = pit_job.log_path
                session.commit()
                _write_log(handle, f"pit_weekly_job={pit_job.id} status={pit_job.status}")
                if pit_job.status != "success":
                    job.status = "failed"
                    job.message = f"pit_weekly_failed={pit_job.status}"
                    job.ended_at = datetime.utcnow()
                    session.commit()
                    _write_log(handle, job.message)
                    return

            if run_pit_fundamentals:
                fund_params = {
                    "start": params.get("fundamental_start"),
                    "end": params.get("fundamental_end"),
                    "refresh_fundamentals": bool(params.get("refresh_fundamentals", False)),
                }
                fund_job = PitFundamentalJob(status="queued", params=fund_params)
                session.add(fund_job)
                session.commit()
                session.refresh(fund_job)
                job.pit_fundamental_job_id = fund_job.id
                session.commit()
                _write_log(handle, f"pit_fundamental_job={fund_job.id} start")
                run_pit_fundamental_job(fund_job.id)
                session.refresh(fund_job)
                job.pit_fundamental_log_path = fund_job.log_path
                session.commit()
                _write_log(handle, f"pit_fundamental_job={fund_job.id} status={fund_job.status}")
                if fund_job.status != "success":
                    job.status = "failed"
                    job.message = f"pit_fundamental_failed={fund_job.status}"
                    job.ended_at = datetime.utcnow()
                    session.commit()
                    _write_log(handle, job.message)
                    return

            if run_backtest:
                _write_log(handle, "backtest start")
                _run_thematic_backtest_task(job.project_id)
                session.expire_all()
                version = _latest_backtest_version(session, job.project_id)
                if not version or not version.content:
                    job.status = "failed"
                    job.message = "backtest_missing_summary"
                    job.backtest_status = "failed"
                    job.ended_at = datetime.utcnow()
                    session.commit()
                    _write_log(handle, job.message)
                    return
                try:
                    summary = json.loads(version.content)
                except json.JSONDecodeError:
                    summary = None
                if not isinstance(summary, dict):
                    job.status = "failed"
                    job.message = "backtest_invalid_summary"
                    job.backtest_status = "failed"
                    job.ended_at = datetime.utcnow()
                    session.commit()
                    _write_log(handle, job.message)
                    return
                job.backtest_status = "failed" if summary.get("status") == "failed" else "success"
                job.backtest_log_path = summary.get("log_path")
                job.backtest_output_dir = summary.get("output_dir")
                job.backtest_artifact_dir = summary.get("artifact_dir")
                session.commit()
                _write_log(handle, f"backtest status={job.backtest_status}")
                if job.backtest_status != "success":
                    job.status = "failed"
                    job.message = "backtest_failed"
                    job.ended_at = datetime.utcnow()
                    session.commit()
                    _write_log(handle, job.message)
                    return

            job.status = "success"
            job.message = "success"
            job.ended_at = datetime.utcnow()
            session.commit()
            _write_log(handle, "done")

        record_audit(
            session,
            action="automation.weekly.success",
            resource_type="auto_weekly_job",
            resource_id=job_id,
            detail={"project_id": job.project_id},
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(AutoWeeklyJob, job_id)
        if job:
            job.status = "failed"
            job.message = str(exc)
            job.ended_at = datetime.utcnow()
            session.commit()
            record_audit(
                session,
                action="automation.weekly.failed",
                resource_type="auto_weekly_job",
                resource_id=job_id,
                detail={"error": str(exc)},
            )
            session.commit()
    finally:
        session.close()
