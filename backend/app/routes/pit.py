from __future__ import annotations

import json
from datetime import datetime
import math
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.core.config import settings
from app.db import get_session
from app.models import PitFundamentalJob, PitWeeklyJob
from app.schemas import (
    PitFundamentalJobCreate,
    PitFundamentalJobOut,
    PitFundamentalJobPageOut,
    PitWeeklyJobCreate,
    PitWeeklyJobOut,
    PitWeeklyJobPageOut,
)
from app.services.audit_log import record_audit
from app.services.pit_runner import run_pit_fundamental_job, run_pit_weekly_job
from app.services.project_symbols import collect_active_project_symbols, write_symbol_list


def _write_progress(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _touch_cancel_flag(job_id: int) -> Path:
    cancel_path = (
        Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}" / "cancel.flag"
    )
    cancel_path.parent.mkdir(parents=True, exist_ok=True)
    cancel_path.write_text("cancel", encoding="utf-8")
    return cancel_path

router = APIRouter(prefix="/api/pit", tags=["pit"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    safe_page = min(max(page, 1), total_pages)
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.get("/weekly-jobs", response_model=list[PitWeeklyJobOut])
def list_weekly_jobs(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    with get_session() as session:
        jobs = (
            session.query(PitWeeklyJob)
            .order_by(PitWeeklyJob.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs


@router.get("/weekly-jobs/page", response_model=PitWeeklyJobPageOut)
def list_weekly_jobs_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(PitWeeklyJob).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(PitWeeklyJob)
            .order_by(PitWeeklyJob.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return PitWeeklyJobPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/weekly-jobs/{job_id}", response_model=PitWeeklyJobOut)
def get_weekly_job(job_id: int):
    with get_session() as session:
        job = session.get(PitWeeklyJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job


@router.get("/weekly-jobs/{job_id}/quality")
def get_weekly_job_quality(job_id: int):
    with get_session() as session:
        job = session.get(PitWeeklyJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
    quality_path = Path(settings.artifact_root) / f"pit_weekly_job_{job_id}" / "quality.json"
    if not quality_path.exists():
        return {"status": job.status, "available": False}
    try:
        payload = json.loads(quality_path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {"status": job.status, "available": False}
    if isinstance(payload, dict):
        payload.setdefault("status", job.status)
        payload.setdefault("available", True)
        return payload
    return {"status": job.status, "available": False}


@router.get("/weekly-jobs/{job_id}/progress")
def get_weekly_job_progress(job_id: int):
    with get_session() as session:
        job = session.get(PitWeeklyJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
    progress_path = Path(settings.artifact_root) / f"pit_weekly_job_{job_id}" / "progress.json"
    if not progress_path.exists():
        return {"stage": "idle", "status": job.status}
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {"stage": "unknown", "status": job.status}
    if isinstance(payload, dict):
        payload.setdefault("status", job.status)
        return payload
    return {"stage": "unknown", "status": job.status}


@router.post("/weekly-jobs", response_model=PitWeeklyJobOut)
def create_weekly_job(payload: PitWeeklyJobCreate, background_tasks: BackgroundTasks):
    params = payload.model_dump()
    with get_session() as session:
        job = PitWeeklyJob(status="queued", params=params)
        session.add(job)
        session.commit()
        session.refresh(job)
        record_audit(
            session,
            action="pit_weekly_job.create",
            resource_type="pit_weekly_job",
            resource_id=job.id,
            detail={"params": params},
        )
        session.commit()
    background_tasks.add_task(run_pit_weekly_job, job.id)
    return job


@router.get("/fundamental-jobs", response_model=list[PitFundamentalJobOut])
def list_fundamental_jobs(
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)
):
    with get_session() as session:
        jobs = (
            session.query(PitFundamentalJob)
            .order_by(PitFundamentalJob.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jobs


@router.get("/fundamental-jobs/page", response_model=PitFundamentalJobPageOut)
def list_fundamental_jobs_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(PitFundamentalJob).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(PitFundamentalJob)
            .order_by(PitFundamentalJob.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return PitFundamentalJobPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/fundamental-jobs/{job_id}", response_model=PitFundamentalJobOut)
def get_fundamental_job(job_id: int):
    with get_session() as session:
        job = session.get(PitFundamentalJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job


@router.get("/fundamental-jobs/{job_id}/progress")
def get_fundamental_job_progress(job_id: int):
    with get_session() as session:
        job = session.get(PitFundamentalJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
    progress_path = (
        Path(settings.artifact_root) / f"pit_fundamental_job_{job_id}" / "progress.json"
    )
    if not progress_path.exists():
        return {"stage": "idle", "status": job.status}
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {"stage": "unknown", "status": job.status}
    if isinstance(payload, dict):
        payload.setdefault("status", job.status)
        return payload
    return {"stage": "unknown", "status": job.status}


@router.post("/fundamental-jobs", response_model=PitFundamentalJobOut)
def create_fundamental_job(
    payload: PitFundamentalJobCreate, background_tasks: BackgroundTasks
):
    params = payload.model_dump()
    if not params.get("refresh_fundamentals") and not params.get(
        "build_pit_fundamentals", True
    ):
        raise HTTPException(status_code=400, detail="至少选择缓存刷新或快照生成")
    project_only = bool(params.get("project_only", True))
    project_symbols: list[str] | None = None
    project_benchmarks: list[str] | None = None
    with get_session() as session:
        if project_only:
            symbols, benchmarks = collect_active_project_symbols(session)
            project_symbols = symbols
            project_benchmarks = benchmarks
            if not project_symbols:
                raise HTTPException(status_code=400, detail="项目标的为空")
            params.pop("symbols", None)
            params.pop("symbol_file", None)
        job = PitFundamentalJob(status="queued", params=params)
        session.add(job)
        session.commit()
        session.refresh(job)
        if project_only and project_symbols:
            log_dir = Path(settings.artifact_root) / f"pit_fundamental_job_{job.id}"
            symbol_path = log_dir / "project_symbols.csv"
            write_symbol_list(symbol_path, project_symbols)
            params["symbol_file"] = str(symbol_path)
            params["symbol_whitelist_count"] = len(project_symbols)
            params["symbol_whitelist_benchmarks"] = project_benchmarks or []
            job.params = params
            session.commit()
        record_audit(
            session,
            action="pit_fundamental_job.create",
            resource_type="pit_fundamental_job",
            resource_id=job.id,
            detail={"params": params},
        )
        session.commit()
    background_tasks.add_task(run_pit_fundamental_job, job.id)
    return job


@router.post("/fundamental-jobs/{job_id}/resume", response_model=PitFundamentalJobOut)
def resume_fundamental_job(job_id: int, background_tasks: BackgroundTasks):
    with get_session() as session:
        job = session.get(PitFundamentalJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        params = dict(job.params or {})
        params["resume_fundamentals"] = True
        params["resume_from_job_id"] = job_id
        new_job = PitFundamentalJob(status="queued", params=params)
        session.add(new_job)
        session.commit()
        session.refresh(new_job)
        record_audit(
            session,
            action="pit_fundamental_job.resume",
            resource_type="pit_fundamental_job",
            resource_id=new_job.id,
            detail={"resume_from": job_id, "params": params},
        )
        session.commit()
    background_tasks.add_task(run_pit_fundamental_job, new_job.id)
    return new_job


@router.post("/fundamental-jobs/{job_id}/cancel", response_model=PitFundamentalJobOut)
def cancel_fundamental_job(job_id: int):
    with get_session() as session:
        job = session.get(PitFundamentalJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status in {"success", "failed", "canceled"}:
            return job
        if job.status == "queued":
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            _write_progress(
                Path(settings.artifact_root)
                / f"pit_fundamental_job_{job_id}"
                / "progress.json",
                {
                    "stage": "canceled",
                    "status": "canceled",
                    "message": job.message,
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
        else:
            if job.status != "cancel_requested":
                job.status = "cancel_requested"
                job.message = "取消中"
            _touch_cancel_flag(job_id)
        record_audit(
            session,
            action="pit_fundamental_job.cancel",
            resource_type="pit_fundamental_job",
            resource_id=job.id,
            detail={"status": job.status},
        )
        session.commit()
        session.refresh(job)
        return job
