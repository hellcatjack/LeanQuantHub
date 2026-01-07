from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import AutoWeeklyJob, Project
from app.schemas import AutoWeeklyJobCreate, AutoWeeklyJobOut
from app.services.audit_log import record_audit
from app.services.automation_runner import run_auto_weekly_job

router = APIRouter(prefix="/api/automation", tags=["automation"])


@router.get("/weekly-jobs", response_model=list[AutoWeeklyJobOut])
def list_weekly_jobs(
    project_id: int | None = Query(default=None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with get_session() as session:
        query = session.query(AutoWeeklyJob).order_by(AutoWeeklyJob.created_at.desc())
        if project_id:
            query = query.filter(AutoWeeklyJob.project_id == project_id)
        return query.offset(offset).limit(limit).all()


@router.get("/weekly-jobs/latest", response_model=AutoWeeklyJobOut)
def latest_weekly_job(project_id: int = Query(...)):
    with get_session() as session:
        job = (
            session.query(AutoWeeklyJob)
            .filter(AutoWeeklyJob.project_id == project_id)
            .order_by(AutoWeeklyJob.created_at.desc())
            .first()
        )
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job


@router.post("/weekly-jobs", response_model=AutoWeeklyJobOut)
def create_weekly_job(payload: AutoWeeklyJobCreate, background_tasks: BackgroundTasks):
    params = payload.model_dump()
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        job = AutoWeeklyJob(project_id=payload.project_id, status="queued", params=params)
        session.add(job)
        session.commit()
        session.refresh(job)
        record_audit(
            session,
            action="automation.weekly.create",
            resource_type="auto_weekly_job",
            resource_id=job.id,
            detail={"project_id": payload.project_id},
        )
        session.commit()
    background_tasks.add_task(run_auto_weekly_job, job.id)
    return job
