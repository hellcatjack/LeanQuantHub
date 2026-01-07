from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import FactorScoreJob, Project
from app.schemas import FactorScoreJobCreate, FactorScoreJobOut
from app.services.audit_log import record_audit
from app.services.factor_score_runner import run_factor_score_job

router = APIRouter(prefix="/api/factor-scores", tags=["factor-scores"])


@router.get("/jobs", response_model=list[FactorScoreJobOut])
def list_factor_jobs(
    project_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with get_session() as session:
        query = session.query(FactorScoreJob).order_by(FactorScoreJob.created_at.desc())
        if project_id is not None:
            query = query.filter(FactorScoreJob.project_id == project_id)
        return query.offset(offset).limit(limit).all()


@router.get("/jobs/{job_id}", response_model=FactorScoreJobOut)
def get_factor_job(job_id: int):
    with get_session() as session:
        job = session.get(FactorScoreJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job


@router.post("/jobs", response_model=FactorScoreJobOut)
def create_factor_job(payload: FactorScoreJobCreate, background_tasks: BackgroundTasks):
    params = payload.model_dump()
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        job = FactorScoreJob(project_id=payload.project_id, status="queued", params=params)
        session.add(job)
        session.commit()
        session.refresh(job)
        record_audit(
            session,
            action="factor_scores.create",
            resource_type="factor_score_job",
            resource_id=job.id,
            detail={"project_id": payload.project_id, "params": params},
        )
        session.commit()
    background_tasks.add_task(run_factor_score_job, job.id)
    return job
