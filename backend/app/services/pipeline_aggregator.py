from __future__ import annotations

from typing import Any

from app.models import AutoWeeklyJob, PreTradeRun, TradeRun


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
