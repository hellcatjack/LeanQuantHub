from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from app.db import get_session
from app.schemas import PipelineRunDetailOut, PipelineRunListOut
from app.services.pipeline_aggregator import build_pipeline_trace, list_pipeline_runs

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/runs", response_model=list[PipelineRunListOut])
def list_runs(
    project_id: int = Query(...),
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    run_type: str | None = Query(default=None, alias="type"),
    started_from: datetime | None = Query(default=None),
    started_to: datetime | None = Query(default=None),
    keyword: str | None = Query(default=None),
):
    with get_session() as session:
        return list_pipeline_runs(
            session,
            project_id=project_id,
            status=status,
            mode=mode,
            run_type=run_type,
            started_from=started_from,
            started_to=started_to,
            keyword=keyword,
        )


@router.get("/runs/{trace_id}", response_model=PipelineRunDetailOut)
def get_trace(trace_id: str):
    with get_session() as session:
        return build_pipeline_trace(session, trace_id=trace_id)
