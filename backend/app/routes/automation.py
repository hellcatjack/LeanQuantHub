from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import AutoWeeklyJob, Project
from app.schemas import (
    AutoWeeklyJobCreate,
    AutoWeeklyJobOut,
    WeeklyRebalanceOut,
    WeeklyRebalanceRequest,
    WeeklyRebalanceStatusOut,
)
from app.services.audit_log import record_audit
from app.services.automation_runner import run_auto_weekly_job
from app.services.weekly_rebalance import (
    execute_weekly_rebalance,
    get_weekly_rebalance_status,
    prepare_weekly_rebalance,
)

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


@router.post("/weekly-rebalance/prepare", response_model=WeeklyRebalanceOut)
def prepare_weekly_rebalance_route(payload: WeeklyRebalanceRequest):
    result = prepare_weekly_rebalance(
        project_id=payload.project_id,
        force=payload.force,
    )
    return WeeklyRebalanceOut(**result.__dict__)


@router.get("/weekly-rebalance/status", response_model=WeeklyRebalanceStatusOut)
def weekly_rebalance_status_route(
    project_id: int | None = Query(default=None),
    limit: int = Query(20, ge=1, le=200),
):
    return WeeklyRebalanceStatusOut(
        **get_weekly_rebalance_status(project_id=project_id, limit=limit)
    )


@router.post("/weekly-rebalance/execute", response_model=WeeklyRebalanceOut)
def execute_weekly_rebalance_route(payload: WeeklyRebalanceRequest):
    result = execute_weekly_rebalance(
        project_id=payload.project_id,
        force=payload.force,
        dry_run=payload.dry_run,
    )
    return WeeklyRebalanceOut(**result.__dict__)
