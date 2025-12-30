from __future__ import annotations

import math

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import (
    AlgorithmVersion,
    BacktestRun,
    Project,
    ProjectAlgorithmBinding,
    Report,
)
from app.schemas import (
    BacktestCompareItem,
    BacktestCompareRequest,
    BacktestCreate,
    BacktestListOut,
    BacktestOut,
    BacktestPageOut,
)
from app.services.audit_log import record_audit
from app.services.lean_runner import run_backtest

router = APIRouter(prefix="/api/backtests", tags=["backtests"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.get("", response_model=list[BacktestOut])
def list_backtests():
    with get_session() as session:
        return session.query(BacktestRun).order_by(BacktestRun.created_at.desc()).all()


@router.get("/page", response_model=BacktestPageOut)
def list_backtests_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(BacktestRun).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        runs = (
            session.query(BacktestRun)
            .order_by(BacktestRun.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        run_ids = [run.id for run in runs]
        report_map: dict[int, int] = {}
        if run_ids:
            reports = (
                session.query(Report)
                .filter(Report.run_id.in_(run_ids), Report.report_type == "html")
                .order_by(Report.created_at.desc())
                .all()
            )
            for report in reports:
                if report.run_id not in report_map:
                    report_map[report.run_id] = report.id
        items: list[BacktestListOut] = []
        for run in runs:
            out = BacktestListOut.model_validate(run, from_attributes=True)
            out.report_id = report_map.get(run.id)
            items.append(out)
        return BacktestPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )

@router.post("", response_model=BacktestOut)
def create_backtest(payload: BacktestCreate, background_tasks: BackgroundTasks):
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        params = payload.params.copy() if isinstance(payload.params, dict) else {}
        binding = (
            session.query(ProjectAlgorithmBinding)
            .filter(ProjectAlgorithmBinding.project_id == payload.project_id)
            .first()
        )
        algorithm_version_id = payload.algorithm_version_id
        if binding:
            if binding.is_locked:
                if algorithm_version_id and algorithm_version_id != binding.algorithm_version_id:
                    raise HTTPException(status_code=400, detail="项目已锁定算法版本")
                algorithm_version_id = binding.algorithm_version_id
            elif algorithm_version_id is None:
                algorithm_version_id = binding.algorithm_version_id
        if algorithm_version_id:
            algo_version = session.get(AlgorithmVersion, algorithm_version_id)
            if not algo_version:
                raise HTTPException(status_code=404, detail="算法版本不存在")
            params["algorithm_version_id"] = algo_version.id
            params["algorithm_id"] = algo_version.algorithm_id
            params["algorithm_version"] = algo_version.version
            if algo_version.language:
                params["algorithm_language"] = algo_version.language
            if algo_version.file_path:
                params["algorithm_path"] = algo_version.file_path
            if algo_version.type_name:
                params["algorithm_type_name"] = algo_version.type_name
        run = BacktestRun(project_id=payload.project_id, params=params)
        session.add(run)
        session.commit()
        session.refresh(run)
        record_audit(
            session,
            action="backtest.create",
            resource_type="backtest",
            resource_id=run.id,
            detail={"project_id": payload.project_id},
        )
        session.commit()

    background_tasks.add_task(run_backtest, run.id)
    return run


@router.get("/{run_id}", response_model=BacktestOut)
def get_backtest(run_id: int):
    with get_session() as session:
        run = session.get(BacktestRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="回测不存在")
        return run


@router.post("/compare", response_model=list[BacktestCompareItem])
def compare_backtests(payload: BacktestCompareRequest):
    run_ids = [run_id for run_id in payload.run_ids if isinstance(run_id, int)]
    if not run_ids:
        raise HTTPException(status_code=400, detail="回测 ID 不能为空")

    with get_session() as session:
        runs = (
            session.query(BacktestRun, Project.name)
            .join(Project, Project.id == BacktestRun.project_id)
            .filter(BacktestRun.id.in_(run_ids))
            .all()
        )

        found_ids = {run.id for run, _ in runs}
        missing = [run_id for run_id in run_ids if run_id not in found_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"回测不存在: {missing}")

        id_to_item = {
            run.id: BacktestCompareItem(
                id=run.id,
                project_id=run.project_id,
                project_name=project_name,
                status=run.status,
                metrics=run.metrics,
                created_at=run.created_at,
                ended_at=run.ended_at,
            )
            for run, project_name in runs
        }
        return [id_to_item[run_id] for run_id in run_ids]
