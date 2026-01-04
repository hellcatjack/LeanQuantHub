from __future__ import annotations

import math

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import MLTrainJob, Project
from app.schemas import MLTrainCreate, MLTrainOut, MLTrainPageOut
from app.services.audit_log import record_audit
from app.services.ml_runner import activate_job, build_ml_config, run_ml_train

router = APIRouter(prefix="/api/ml", tags=["ml"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.get("/train-jobs", response_model=list[MLTrainOut])
def list_train_jobs(project_id: int | None = Query(None)):
    with get_session() as session:
        query = session.query(MLTrainJob)
        if project_id:
            query = query.filter(MLTrainJob.project_id == project_id)
        return query.order_by(MLTrainJob.created_at.desc()).all()


@router.get("/train-jobs/page", response_model=MLTrainPageOut)
def list_train_jobs_page(
    project_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        query = session.query(MLTrainJob)
        if project_id:
            query = query.filter(MLTrainJob.project_id == project_id)
        total = query.count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            query.order_by(MLTrainJob.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return MLTrainPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.post("/train-jobs", response_model=MLTrainOut)
def create_train_job(payload: MLTrainCreate, background_tasks: BackgroundTasks):
    overrides = {
        "device": payload.device,
        "train_years": payload.train_years,
        "valid_months": payload.valid_months,
        "label_horizon_days": payload.label_horizon_days,
    }
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        config = build_ml_config(session, payload.project_id, overrides)
        job = MLTrainJob(
            project_id=payload.project_id,
            status="queued",
            config=config,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        record_audit(
            session,
            action="ml.train.create",
            resource_type="ml_train_job",
            resource_id=job.id,
            detail={"project_id": payload.project_id},
        )
        session.commit()

    background_tasks.add_task(run_ml_train, job.id)
    return job


@router.get("/train-jobs/{job_id}", response_model=MLTrainOut)
def get_train_job(job_id: int):
    with get_session() as session:
        job = session.get(MLTrainJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        return job


@router.post("/train-jobs/{job_id}/activate", response_model=MLTrainOut)
def activate_train_job(job_id: int):
    with get_session() as session:
        job = session.get(MLTrainJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        if not job.output_dir:
            raise HTTPException(status_code=400, detail="训练产物不存在")
        activate_job(session, job)
        record_audit(
            session,
            action="ml.train.activate",
            resource_type="ml_train_job",
            resource_id=job.id,
            detail={"project_id": job.project_id},
        )
        session.commit()
        session.refresh(job)
        return job
