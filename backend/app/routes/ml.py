from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import MLTrainJob, MLPipelineRun, Project
from app.schemas import MLTrainCreate, MLTrainOut, MLTrainPageOut
from app.services.audit_log import record_audit
from app.services.ml_runner import (
    activate_job,
    build_ml_config,
    run_ml_train,
    _attach_data_ranges,
)

router = APIRouter(prefix="/api/ml", tags=["ml"])

MAX_PAGE_SIZE = 200


def _read_progress(output_dir: str | None) -> dict | None:
    if not output_dir:
        return None
    progress_path = Path(output_dir) / "progress.json"
    if not progress_path.exists():
        return None
    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _with_progress(job: MLTrainJob) -> MLTrainOut:
    out = MLTrainOut.model_validate(job, from_attributes=True)
    progress = _read_progress(job.output_dir)
    if progress:
        out.progress = progress.get("progress")
        out.progress_detail = progress
    out.metrics = _attach_data_ranges(out.metrics, out.output_dir)
    return out


def _touch_cancel_flag(output_dir: str | None) -> None:
    if not output_dir:
        return
    cancel_path = Path(output_dir) / "cancel.flag"
    cancel_path.parent.mkdir(parents=True, exist_ok=True)
    cancel_path.write_text("cancel", encoding="utf-8")


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
        jobs = query.order_by(MLTrainJob.created_at.desc()).all()
        return [_with_progress(job) for job in jobs]


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
            items=[_with_progress(job) for job in items],
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
        "test_months": payload.test_months,
        "step_months": payload.step_months,
        "label_horizon_days": payload.label_horizon_days,
        "train_start_year": payload.train_start_year,
        "model_type": payload.model_type,
        "model_params": payload.model_params,
    }
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        pipeline_id = payload.pipeline_id
        if pipeline_id is not None:
            pipeline = session.get(MLPipelineRun, pipeline_id)
            if not pipeline or pipeline.project_id != payload.project_id:
                raise HTTPException(status_code=404, detail="Pipeline 不存在")
        config = build_ml_config(session, payload.project_id, overrides)
        job = MLTrainJob(
            project_id=payload.project_id,
            status="queued",
            config=config,
            pipeline_id=pipeline_id,
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
        return _with_progress(job)


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


@router.post("/train-jobs/{job_id}/cancel", response_model=MLTrainOut)
def cancel_train_job(job_id: int):
    with get_session() as session:
        job = session.get(MLTrainJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        if job.status in {"success", "failed", "canceled"}:
            return _with_progress(job)
        if job.status == "queued":
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
        else:
            if job.status != "cancel_requested":
                job.status = "cancel_requested"
                job.message = "取消中"
            _touch_cancel_flag(job.output_dir)
        record_audit(
            session,
            action="ml.train.cancel",
            resource_type="ml_train_job",
            resource_id=job.id,
            detail={"project_id": job.project_id, "status": job.status},
        )
        session.commit()
        session.refresh(job)
        return _with_progress(job)
