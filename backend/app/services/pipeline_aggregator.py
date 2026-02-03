from __future__ import annotations

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
    return items


def build_pipeline_trace(session, *, trace_id: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []

    if trace_id.startswith("pretrade:"):
        run_id = int(trace_id.split(":", 1)[1])
        run = session.get(PreTradeRun, run_id)
        if not run:
            return {"trace_id": trace_id, "events": [], "warnings": ["pretrade_run_missing"]}
        events.append(
            {
                "event_id": f"pretrade_run:{run.id}",
                "task_type": "pretrade_run",
                "task_id": run.id,
                "stage": "pretrade_gate",
                "status": run.status,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "message": run.message,
            }
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
                {
                    "event_id": f"pretrade_step:{step.id}",
                    "task_type": "pretrade_step",
                    "task_id": step.id,
                    "stage": "pretrade_gate",
                    "status": step.status,
                    "started_at": step.started_at,
                    "ended_at": step.ended_at,
                    "message": step.message,
                    "params_snapshot": step.params,
                    "artifact_paths": step.artifacts,
                }
            )
            if isinstance(step.artifacts, dict):
                snapshot_id = snapshot_id or step.artifacts.get("decision_snapshot_id")
                trade_run_id = trade_run_id or step.artifacts.get("trade_run_id")
        if snapshot_id:
            snapshot = session.get(DecisionSnapshot, int(snapshot_id))
            if snapshot:
                events.append(
                    {
                        "event_id": f"decision_snapshot:{snapshot.id}",
                        "task_type": "decision_snapshot",
                        "task_id": snapshot.id,
                        "stage": "decision_snapshot",
                        "status": snapshot.status,
                        "started_at": snapshot.started_at,
                        "ended_at": snapshot.ended_at,
                        "message": snapshot.message,
                        "artifact_paths": {
                            "summary": snapshot.summary_path,
                            "items": snapshot.items_path,
                            "filters": snapshot.filters_path,
                        },
                    }
                )
            else:
                warnings.append("decision_snapshot_missing")
        if trade_run_id:
            trade_run = session.get(TradeRun, int(trade_run_id))
            if trade_run:
                events.append(
                    {
                        "event_id": f"trade_run:{trade_run.id}",
                        "task_type": "trade_run",
                        "task_id": trade_run.id,
                        "stage": "trade_execute",
                        "status": trade_run.status,
                        "started_at": trade_run.started_at,
                        "ended_at": trade_run.ended_at,
                        "message": trade_run.message,
                        "params_snapshot": trade_run.params,
                    }
                )
                orders = (
                    session.query(TradeOrder)
                    .filter(TradeOrder.run_id == trade_run.id)
                    .order_by(TradeOrder.created_at.asc())
                    .all()
                )
                for order in orders:
                    events.append(
                        {
                            "event_id": f"trade_order:{order.id}",
                            "task_type": "trade_order",
                            "task_id": order.id,
                            "stage": "trade_execute",
                            "status": order.status,
                            "started_at": order.created_at,
                            "ended_at": order.updated_at,
                        }
                    )
            else:
                warnings.append("trade_run_missing")
        return {"trace_id": trace_id, "events": events, "warnings": warnings}
    return {"trace_id": trace_id, "events": [], "warnings": ["trace_type_unknown"]}
