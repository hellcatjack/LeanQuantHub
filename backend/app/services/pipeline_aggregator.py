from __future__ import annotations

from typing import Any

from app.models import PreTradeRun, TradeRun


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
