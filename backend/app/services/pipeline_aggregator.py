from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import (
    AuditLog,
    AutoWeeklyJob,
    DecisionSnapshot,
    PitFundamentalJob,
    PitWeeklyJob,
    PreTradeRun,
    PreTradeStep,
    TradeFill,
    TradeOrder,
    TradeRun,
)


def list_pipeline_runs(
    session,
    *,
    project_id: int,
    status: str | None = None,
    mode: str | None = None,
    run_type: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
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
    filtered = _filter_pipeline_runs(
        session,
        items,
        status=status,
        mode=mode,
        run_type=run_type,
        started_from=started_from,
        started_to=started_to,
        keyword=keyword,
    )
    filtered.sort(key=_run_sort_key, reverse=True)
    return filtered


def _run_sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
    when = item.get("created_at") or item.get("started_at") or item.get("ended_at")
    if when is None:
        when = datetime.min
    return when, item.get("trace_id", "")


def _filter_pipeline_runs(
    session,
    items: list[dict[str, Any]],
    *,
    status: str | None,
    mode: str | None,
    run_type: str | None,
    started_from: datetime | None,
    started_to: datetime | None,
    keyword: str | None,
) -> list[dict[str, Any]]:
    normalized_status = str(status or "").strip().lower()
    normalized_mode = str(mode or "").strip().lower()
    normalized_type = str(run_type or "").strip().lower()
    normalized_keyword = str(keyword or "").strip().lower()
    tags_cache: dict[str, list[str]] = {}

    filtered: list[dict[str, Any]] = []
    for item in items:
        item_status = str(item.get("status") or "").strip().lower()
        item_mode = str(item.get("mode") or "").strip().lower()
        item_type = str(item.get("run_type") or "").strip().lower()
        if normalized_status and item_status != normalized_status:
            continue
        if normalized_mode and item_mode != normalized_mode:
            continue
        if normalized_type and item_type != normalized_type:
            continue

        when = item.get("created_at") or item.get("started_at") or item.get("ended_at")
        if started_from and (when is None or when < started_from):
            continue
        if started_to and (when is None or when > started_to):
            continue

        if normalized_keyword:
            trace_id = str(item.get("trace_id") or "")
            trace_match = normalized_keyword in trace_id.lower()
            if not trace_match:
                if trace_id not in tags_cache:
                    tags_cache[trace_id] = _collect_trace_tags(session, trace_id)
                tag_match = any(
                    normalized_keyword in tag.lower() for tag in tags_cache[trace_id]
                )
                if not tag_match:
                    continue
        filtered.append(item)
    return filtered


def _collect_trace_tags(session, trace_id: str) -> list[str]:
    if trace_id.startswith("pretrade:"):
        return _collect_pretrade_tags(session, int(trace_id.split(":", 1)[1]))
    if trace_id.startswith("trade:"):
        return _collect_trade_tags(session, int(trace_id.split(":", 1)[1]))
    if trace_id.startswith("auto:"):
        return _collect_auto_tags(session, int(trace_id.split(":", 1)[1]))
    return []


def _collect_pretrade_tags(session, run_id: int) -> list[str]:
    tags: set[str] = {str(run_id)}
    steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run_id).all()
    trade_run_ids: set[int] = set()
    for step in steps:
        tags.add(str(step.id))
        if isinstance(step.artifacts, dict):
            snapshot_id = step.artifacts.get("decision_snapshot_id")
            trade_run_id = step.artifacts.get("trade_run_id")
            if snapshot_id:
                tags.add(str(snapshot_id))
            if trade_run_id:
                trade_run_ids.add(int(trade_run_id))
                tags.add(str(trade_run_id))
    for trade_run_id in trade_run_ids:
        tags.update(_collect_trade_tags(session, trade_run_id))
    return sorted(tags)


def _collect_trade_tags(session, run_id: int) -> list[str]:
    tags: set[str] = {str(run_id)}
    orders = session.query(TradeOrder).filter(TradeOrder.run_id == run_id).all()
    order_ids = [order.id for order in orders]
    tags.update(str(order_id) for order_id in order_ids)
    if order_ids:
        fills = session.query(TradeFill).filter(TradeFill.order_id.in_(order_ids)).all()
        tags.update(str(fill.id) for fill in fills)
    return sorted(tags)


def _collect_auto_tags(session, job_id: int) -> list[str]:
    tags: set[str] = {str(job_id)}
    job = session.get(AutoWeeklyJob, job_id)
    if job:
        if job.pit_weekly_job_id:
            tags.add(str(job.pit_weekly_job_id))
        if job.pit_fundamental_job_id:
            tags.add(str(job.pit_fundamental_job_id))
    return sorted(tags)


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
                    fills = (
                        session.query(TradeFill)
                        .filter(TradeFill.order_id == order.id)
                        .order_by(TradeFill.created_at.asc())
                        .all()
                    )
                    for fill in fills:
                        events.append(
                            _build_event(
                                event_id=f"trade_fill:{fill.id}",
                                task_type="trade_fill",
                                task_id=fill.id,
                                stage="trade_execute",
                                status="filled",
                                started_at=fill.fill_time or fill.created_at,
                                ended_at=fill.created_at,
                                params_snapshot=fill.params,
                                parent_id=f"trade_order:{order.id}",
                                tags=[str(fill.id), str(order.id), str(trade_run.id)],
                            )
                        )
            else:
                warnings.append("trade_run_missing")
        _append_audit_events(
            session,
            events,
            resource_type="pretrade_run",
            resource_id=run.id,
            parent_id=f"pretrade_run:{run.id}",
        )
        events.sort(key=_event_sort_key)
        return {"trace_id": trace_id, "events": events, "warnings": warnings}
    if trace_id.startswith("auto:"):
        job_id = int(trace_id.split(":", 1)[1])
        job = session.get(AutoWeeklyJob, job_id)
        if not job:
            return {"trace_id": trace_id, "events": [], "warnings": ["auto_weekly_missing"]}
        events.append(
            _build_event(
                event_id=f"auto_weekly:{job.id}",
                task_type="auto_weekly",
                task_id=job.id,
                stage="data_prepare",
                status=job.status,
                started_at=job.started_at,
                ended_at=job.ended_at,
                message=job.message,
                error_code=job.message if job.status in {"failed", "blocked"} else None,
                params_snapshot=job.params,
                artifact_paths={
                    "backtest_output_dir": job.backtest_output_dir,
                    "backtest_artifact_dir": job.backtest_artifact_dir,
                },
                log_path=job.log_path,
                tags=[str(job.id)],
            )
        )
        if job.pit_weekly_job_id:
            pit_weekly = session.get(PitWeeklyJob, job.pit_weekly_job_id)
            if pit_weekly:
                events.append(
                    _build_event(
                        event_id=f"pit_weekly:{pit_weekly.id}",
                        task_type="pit_weekly",
                        task_id=pit_weekly.id,
                        stage="data_prepare",
                        status=pit_weekly.status,
                        started_at=pit_weekly.started_at,
                        ended_at=pit_weekly.ended_at,
                        message=pit_weekly.message,
                        error_code=pit_weekly.message
                        if pit_weekly.status in {"failed", "blocked"}
                        else None,
                        params_snapshot=pit_weekly.params,
                        artifact_paths={
                            "output_dir": pit_weekly.output_dir,
                            "last_snapshot": pit_weekly.last_snapshot_path,
                        },
                        log_path=pit_weekly.log_path,
                        parent_id=f"auto_weekly:{job.id}",
                        tags=[str(pit_weekly.id), str(job.id)],
                    )
                )
            else:
                warnings.append("pit_weekly_missing")
        if job.pit_fundamental_job_id:
            pit_fundamental = session.get(PitFundamentalJob, job.pit_fundamental_job_id)
            if pit_fundamental:
                events.append(
                    _build_event(
                        event_id=f"pit_fundamental:{pit_fundamental.id}",
                        task_type="pit_fundamental",
                        task_id=pit_fundamental.id,
                        stage="data_prepare",
                        status=pit_fundamental.status,
                        started_at=pit_fundamental.started_at,
                        ended_at=pit_fundamental.ended_at,
                        message=pit_fundamental.message,
                        error_code=pit_fundamental.message
                        if pit_fundamental.status in {"failed", "blocked"}
                        else None,
                        params_snapshot=pit_fundamental.params,
                        artifact_paths={
                            "output_dir": pit_fundamental.output_dir,
                            "last_snapshot": pit_fundamental.last_snapshot_path,
                        },
                        log_path=pit_fundamental.log_path,
                        parent_id=f"auto_weekly:{job.id}",
                        tags=[str(pit_fundamental.id), str(job.id)],
                    )
                )
            else:
                warnings.append("pit_fundamental_missing")
        if job.backtest_status or job.backtest_log_path or job.backtest_output_dir:
            events.append(
                _build_event(
                    event_id=f"backtest:{job.id}",
                    task_type="backtest",
                    task_id=job.id,
                    stage="data_prepare",
                    status=job.backtest_status,
                    started_at=job.started_at,
                    ended_at=job.ended_at,
                    message=job.message,
                    error_code=job.message if job.backtest_status == "failed" else None,
                    artifact_paths={
                        "output_dir": job.backtest_output_dir,
                        "artifact_dir": job.backtest_artifact_dir,
                    },
                    log_path=job.backtest_log_path,
                    parent_id=f"auto_weekly:{job.id}",
                    tags=[str(job.id)],
                )
            )
        _append_audit_events(
            session,
            events,
            resource_type="auto_weekly_job",
            resource_id=job.id,
            parent_id=f"auto_weekly:{job.id}",
        )
        events.sort(key=_event_sort_key)
        return {"trace_id": trace_id, "events": events, "warnings": warnings}
    if trace_id.startswith("trade:"):
        run_id = int(trace_id.split(":", 1)[1])
        run = session.get(TradeRun, run_id)
        if not run:
            return {"trace_id": trace_id, "events": [], "warnings": ["trade_run_missing"]}
        events.append(
            _build_event(
                event_id=f"trade_run:{run.id}",
                task_type="trade_run",
                task_id=run.id,
                stage="trade_execute",
                status=run.status,
                started_at=run.started_at,
                ended_at=run.ended_at,
                message=run.message,
                error_code=run.message if run.status in {"failed", "blocked"} else None,
                params_snapshot=run.params,
                tags=[str(run.id)],
            )
        )
        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
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
                    parent_id=f"trade_run:{run.id}",
                    tags=[str(order.id), str(run.id)],
                )
            )
            fills = (
                session.query(TradeFill)
                .filter(TradeFill.order_id == order.id)
                .order_by(TradeFill.created_at.asc())
                .all()
            )
            for fill in fills:
                events.append(
                    _build_event(
                        event_id=f"trade_fill:{fill.id}",
                        task_type="trade_fill",
                        task_id=fill.id,
                        stage="trade_execute",
                        status="filled",
                        started_at=fill.fill_time or fill.created_at,
                        ended_at=fill.created_at,
                        params_snapshot=fill.params,
                        parent_id=f"trade_order:{order.id}",
                        tags=[str(fill.id), str(order.id), str(run.id)],
                    )
                )
        _append_audit_events(
            session,
            events,
            resource_type="trade_run",
            resource_id=run.id,
            parent_id=f"trade_run:{run.id}",
        )
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


def _append_audit_events(
    session,
    events: list[dict[str, Any]],
    *,
    resource_type: str,
    resource_id: int | None,
    parent_id: str | None,
) -> None:
    if resource_id is None:
        return
    logs = (
        session.query(AuditLog)
        .filter(
            AuditLog.resource_type == resource_type,
            AuditLog.resource_id == resource_id,
        )
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    for log in logs:
        events.append(
            _build_event(
                event_id=f"audit_log:{log.id}",
                task_type="audit_log",
                task_id=log.id,
                stage="audit_log",
                status=None,
                started_at=log.created_at,
                ended_at=log.created_at,
                message=log.action,
                params_snapshot=log.detail,
                parent_id=parent_id,
                tags=[str(log.id), str(resource_id)],
            )
        )
