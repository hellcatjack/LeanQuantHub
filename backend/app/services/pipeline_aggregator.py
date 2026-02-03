from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import (
    AutoWeeklyJob,
    DecisionSnapshot,
    PreTradeRun,
    PreTradeStep,
    TradeOrder,
    TradeRun,
)


def list_pipeline_runs(session, *, project_id: int) -> list[dict[str, Any]]:
    pretrade_runs = (
        session.query(PreTradeRun)
        .filter(PreTradeRun.project_id == project_id)
        .order_by(PreTradeRun.created_at.desc())
        .all()
    )
    trade_runs = (
        session.query(TradeRun)
        .filter(TradeRun.project_id == project_id)
        .order_by(TradeRun.created_at.desc())
        .all()
    )
    weekly_jobs = (
        session.query(AutoWeeklyJob)
        .filter(AutoWeeklyJob.project_id == project_id)
        .order_by(AutoWeeklyJob.created_at.desc())
        .all()
    )

    items: list[dict[str, Any]] = []
    for run in pretrade_runs:
        items.append(
            {
                "trace_id": f"pretrade:{run.id}",
                "run_type": "pretrade",
                "project_id": run.project_id,
                "status": run.status,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "created_at": run.created_at,
            }
        )
    for job in weekly_jobs:
        items.append(
            {
                "trace_id": f"auto:{job.id}",
                "run_type": "auto_weekly",
                "project_id": job.project_id,
                "status": job.status,
                "started_at": job.started_at,
                "ended_at": job.ended_at,
                "created_at": job.created_at,
            }
        )
    for run in trade_runs:
        if (run.params or {}).get("pretrade_run_id"):
            continue
        items.append(
            {
                "trace_id": f"trade:{run.id}",
                "run_type": "trade",
                "project_id": run.project_id,
                "status": run.status,
                "mode": run.mode,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "created_at": run.created_at,
            }
        )
    items.sort(key=_run_sort_key, reverse=True)
    return items


def _run_sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
    when = item.get("created_at") or item.get("started_at") or item.get("ended_at")
    if when is None:
        when = datetime.min
    return when, item.get("trace_id", "")


def build_pipeline_trace(session, *, trace_id: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []

    if trace_id.startswith("pretrade:"):
        run_id = int(trace_id.split(":", 1)[1])
        run = session.get(PreTradeRun, run_id)
        if not run:
            return {"trace_id": trace_id, "events": [], "warnings": ["pretrade_run_missing"]}
        events.append(
            _build_event(
                event_id=f"pretrade_run:{run.id}",
                task_type="pretrade_run",
                task_id=run.id,
                stage="pretrade_gate",
                status=run.status,
                started_at=run.started_at,
                ended_at=run.ended_at,
                message=run.message,
                error_code=run.message if run.status in {"failed", "blocked"} else None,
                tags=[str(run.id)],
            )
        )
        steps = (
            session.query(PreTradeStep)
            .filter(PreTradeStep.run_id == run.id)
            .order_by(PreTradeStep.step_order.asc())
            .all()
        )
        snapshot_id = None
        trade_run_id = None
        for step in steps:
            events.append(
                _build_event(
                    event_id=f"pretrade_step:{step.id}",
                    task_type="pretrade_step",
                    task_id=step.id,
                    stage="pretrade_gate",
                    status=step.status,
                    started_at=step.started_at,
                    ended_at=step.ended_at,
                    message=step.message,
                    error_code=step.message if step.status in {"failed", "blocked"} else None,
                    params_snapshot=step.params,
                    artifact_paths=step.artifacts,
                    log_path=step.log_path,
                    parent_id=f"pretrade_run:{run.id}",
                    tags=[str(step.id), str(run.id)],
                )
            )
            if isinstance(step.artifacts, dict):
                snapshot_id = snapshot_id or step.artifacts.get("decision_snapshot_id")
                trade_run_id = trade_run_id or step.artifacts.get("trade_run_id")
        if snapshot_id:
            snapshot = session.get(DecisionSnapshot, int(snapshot_id))
            if snapshot:
                events.append(
                    _build_event(
                        event_id=f"decision_snapshot:{snapshot.id}",
                        task_type="decision_snapshot",
                        task_id=snapshot.id,
                        stage="decision_snapshot",
                        status=snapshot.status,
                        started_at=snapshot.started_at,
                        ended_at=snapshot.ended_at,
                        message=snapshot.message,
                        error_code=snapshot.message
                        if snapshot.status in {"failed", "blocked"}
                        else None,
                        artifact_paths={
                            "summary": snapshot.summary_path,
                            "items": snapshot.items_path,
                            "filters": snapshot.filters_path,
                        },
                        log_path=snapshot.log_path,
                        parent_id=f"pretrade_run:{run.id}",
                        tags=[str(snapshot.id), str(run.id)],
                    )
                )
            else:
                warnings.append("decision_snapshot_missing")
        if trade_run_id:
            trade_run = session.get(TradeRun, int(trade_run_id))
            if trade_run:
                events.append(
                    _build_event(
                        event_id=f"trade_run:{trade_run.id}",
                        task_type="trade_run",
                        task_id=trade_run.id,
                        stage="trade_execute",
                        status=trade_run.status,
                        started_at=trade_run.started_at,
                        ended_at=trade_run.ended_at,
                        message=trade_run.message,
                        error_code=trade_run.message
                        if trade_run.status in {"failed", "blocked"}
                        else None,
                        params_snapshot=trade_run.params,
                        parent_id=f"pretrade_run:{run.id}",
                        tags=[str(trade_run.id), str(run.id)],
                    )
                )
                orders = (
                    session.query(TradeOrder)
                    .filter(TradeOrder.run_id == trade_run.id)
                    .order_by(TradeOrder.created_at.asc())
                    .all()
                )
                for order in orders:
                    events.append(
                        _build_event(
                            event_id=f"trade_order:{order.id}",
                            task_type="trade_order",
                            task_id=order.id,
                            stage="trade_execute",
                            status=order.status,
                            started_at=order.created_at,
                            ended_at=order.updated_at,
                            params_snapshot=order.params,
                            parent_id=f"trade_run:{trade_run.id}",
                            tags=[str(order.id), str(trade_run.id)],
                        )
                    )
            else:
                warnings.append("trade_run_missing")
        events.sort(key=_event_sort_key)
        return {"trace_id": trace_id, "events": events, "warnings": warnings}
    return {"trace_id": trace_id, "events": [], "warnings": ["trace_type_unknown"]}


def _event_sort_key(event: dict[str, Any]) -> tuple[datetime, str]:
    when = event.get("started_at") or event.get("ended_at")
    if when is None:
        when = datetime.min
    return when, event.get("event_id", "")


def _build_event(
    *,
    event_id: str,
    task_type: str,
    task_id: int | None,
    stage: str | None,
    status: str | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    message: str | None = None,
    error_code: str | None = None,
    params_snapshot: dict | None = None,
    artifact_paths: dict | None = None,
    log_path: str | None = None,
    parent_id: str | None = None,
    retry_of: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "task_type": task_type,
        "task_id": task_id,
        "stage": stage,
        "status": status,
        "message": message,
        "error_code": error_code,
        "started_at": started_at,
        "ended_at": ended_at,
        "params_snapshot": params_snapshot,
        "artifact_paths": artifact_paths,
        "log_path": log_path,
        "parent_id": parent_id,
        "retry_of": retry_of,
        "tags": tags or [],
    }
