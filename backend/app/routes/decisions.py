from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import DecisionSnapshot
from app.schemas import (
    DecisionSnapshotDetailOut,
    DecisionSnapshotOut,
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
