from __future__ import annotations

import math
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import settings
from app.db import get_session
from app.models import BacktestRun, Report
from app.schemas import ReportOut, ReportPageOut

router = APIRouter(prefix="/api/reports", tags=["reports"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.get("", response_model=list[ReportOut])
def list_reports(run_id: int | None = Query(default=None)):
    with get_session() as session:
        query = session.query(Report)
        if run_id is not None:
            run = session.get(BacktestRun, run_id)
            if not run:
                raise HTTPException(status_code=404, detail="回测不存在")
            query = query.filter(Report.run_id == run_id)
        return query.order_by(Report.created_at.desc()).all()


@router.get("/page", response_model=ReportPageOut)
def list_reports_page(
    run_id: int | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        query = session.query(Report)
        if run_id is not None:
            run = session.get(BacktestRun, run_id)
            if not run:
                raise HTTPException(status_code=404, detail="回测不存在")
            query = query.filter(Report.run_id == run_id)
        total = query.count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            query.order_by(Report.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return ReportPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/{report_id}/file")
def get_report_file(report_id: int, download: bool = Query(default=False)):
    with get_session() as session:
        report = session.get(Report, report_id)
        if not report:
            raise HTTPException(status_code=404, detail="报告不存在")

    path = Path(report.path).resolve()
    root = Path(settings.artifact_root).resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=400, detail="报告路径非法")
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")

    suffix = path.suffix.lower()
    if suffix == ".html":
        media_type = "text/html"
    elif suffix in {".log", ".txt"}:
        media_type = "text/plain"
    else:
        media_type = "application/json"

    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{path.name}"'}
    return FileResponse(path, media_type=media_type, headers=headers)
