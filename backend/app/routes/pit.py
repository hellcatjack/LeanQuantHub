from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.core.config import settings
from app.db import get_session
from app.models import PitFundamentalJob, PitWeeklyJob
from app.schemas import (
    PitFundamentalJobCreate,
    PitFundamentalJobOut,
    PitWeeklyJobCreate,
    PitWeeklyJobOut,
)
from app.services.audit_log import record_audit
from app.services.pit_runner import run_pit_fundamental_job, run_pit_weekly_job

router = APIRouter(prefix="/api/pit", tags=["pit"])


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
    with get_session() as session:
        job = PitFundamentalJob(status="queued", params=params)
        session.add(job)
        session.commit()
        session.refresh(job)
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
