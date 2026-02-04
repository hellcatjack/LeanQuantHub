from __future__ import annotations

from datetime import datetime
import math

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import String, cast, or_

from app.db import get_session
from app.models import DecisionSnapshot
from app.schemas import (
    DecisionSnapshotDetailOut,
    DecisionSnapshotOut,
    DecisionSnapshotPageOut,
    DecisionSnapshotPreviewOut,
    DecisionSnapshotRequest,
)
from app.services.audit_log import record_audit
from app.services.decision_snapshot import (
    build_preview_decision_snapshot,
    load_decision_snapshot_detail,
    run_decision_snapshot_task,
)

router = APIRouter(prefix="/api/decisions", tags=["decisions"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.post("/preview", response_model=DecisionSnapshotPreviewOut)
def preview_decision_snapshot(payload: DecisionSnapshotRequest):
    with get_session() as session:
        try:
            result = build_preview_decision_snapshot(session, payload.model_dump())
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return DecisionSnapshotPreviewOut(
            id=None,
            project_id=payload.project_id,
            pipeline_id=payload.pipeline_id,
            train_job_id=payload.train_job_id,
            status="preview",
            snapshot_date=(result.get("summary") or {}).get("snapshot_date"),
            params=result.get("params"),
            summary=result.get("summary"),
            artifact_dir=result.get("artifact_dir"),
            summary_path=result.get("summary_path"),
            items_path=result.get("items_path"),
            filters_path=result.get("filters_path"),
            message=None,
            items=result.get("items") or [],
            filters=result.get("filters") or [],
        )


@router.post("/run", response_model=DecisionSnapshotOut)
def run_decision_snapshot(payload: DecisionSnapshotRequest, background_tasks: BackgroundTasks):
    with get_session() as session:
        snapshot = DecisionSnapshot(
            project_id=payload.project_id,
            pipeline_id=payload.pipeline_id,
            train_job_id=payload.train_job_id,
            status="queued",
            snapshot_date=payload.snapshot_date,
            params=payload.model_dump(),
            created_at=datetime.utcnow(),
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        record_audit(
            session,
            action="decision.snapshot.create",
            resource_type="decision_snapshot",
            resource_id=snapshot.id,
            detail={"project_id": payload.project_id},
        )
        session.commit()
        background_tasks.add_task(run_decision_snapshot_task, snapshot.id)
        return DecisionSnapshotOut.model_validate(snapshot, from_attributes=True)


@router.get("", response_model=DecisionSnapshotPageOut)
def list_decision_snapshots_page(
    project_id: int = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    status: str | None = None,
    snapshot_date: str | None = None,
    backtest_run_id: int | None = None,
    keyword: str | None = None,
):
    with get_session() as session:
        query = session.query(DecisionSnapshot).filter(
            DecisionSnapshot.project_id == project_id
        )
        if status:
            query = query.filter(DecisionSnapshot.status == status)
        if snapshot_date:
            query = query.filter(DecisionSnapshot.snapshot_date == snapshot_date)
        if backtest_run_id is not None:
            query = query.filter(DecisionSnapshot.backtest_run_id == backtest_run_id)
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(
                or_(
                    cast(DecisionSnapshot.id, String).like(like),
                    cast(DecisionSnapshot.pipeline_id, String).like(like),
                    cast(DecisionSnapshot.train_job_id, String).like(like),
                )
            )
        total = query.count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            query.order_by(DecisionSnapshot.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return DecisionSnapshotPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/latest", response_model=DecisionSnapshotDetailOut)
def get_latest_snapshot(project_id: int = Query(...)):
    with get_session() as session:
        snapshot = (
            session.query(DecisionSnapshot)
            .filter(DecisionSnapshot.project_id == project_id)
            .order_by(DecisionSnapshot.created_at.desc())
            .first()
        )
        if not snapshot:
            raise HTTPException(status_code=404, detail="snapshot not found")
        payload = DecisionSnapshotDetailOut.model_validate(snapshot, from_attributes=True)
        detail = load_decision_snapshot_detail(snapshot)
        payload.summary = detail.get("summary") or snapshot.summary
        payload.items = detail.get("items") or []
        payload.filters = detail.get("filters") or []
        return payload


@router.get("/{snapshot_id}", response_model=DecisionSnapshotDetailOut)
def get_snapshot_detail(snapshot_id: int):
    with get_session() as session:
        snapshot = session.get(DecisionSnapshot, snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="snapshot not found")
        payload = DecisionSnapshotDetailOut.model_validate(snapshot, from_attributes=True)
        detail = load_decision_snapshot_detail(snapshot)
        payload.summary = detail.get("summary") or snapshot.summary
        payload.items = detail.get("items") or []
        payload.filters = detail.get("filters") or []
        return payload
