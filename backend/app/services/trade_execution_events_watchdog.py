from __future__ import annotations

from pathlib import Path

from app.models import TradeOrder, TradeRun
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_open_orders, read_positions
from app.services.lean_execution import ingest_execution_events
from app.services.trade_cancel import reconcile_cancel_requested_orders
from app.services.trade_open_orders_sync import sync_trade_orders_from_open_orders
from app.services.trade_executor import (
    reconcile_run_with_positions,
    recompute_trade_run_completion_summary,
)

ACTIVE_ORDER_STATUSES = ("NEW", "SUBMITTED", "PARTIAL", "CANCEL_REQUESTED")
LOW_CONF_RECOVERY_STATUSES = ("CANCELED", "CANCELLED", "SKIPPED")


def _normalize_status(value: object) -> str:
    return str(value or "").strip().upper()


def _is_low_conf_missing(params: object) -> bool:
    if not isinstance(params, dict):
        return False
    return str(params.get("sync_reason") or "").strip() == "missing_from_open_orders"


def _extract_open_tags(payload: dict | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    tags: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").strip()
        if tag:
            tags.add(tag)
    return tags


def _resolve_run_events_path(session, run_id: int) -> Path | None:
    run = session.get(TradeRun, int(run_id))
    if run is None or not isinstance(run.params, dict):
        return None
    lean_exec = run.params.get("lean_execution")
    if not isinstance(lean_exec, dict):
        return None
    output_dir = lean_exec.get("output_dir")
    if not output_dir:
        return None
    return Path(str(output_dir)) / "execution_events.jsonl"


def ingest_active_trade_order_events(
    session,
    *,
    bridge_root: Path | None = None,
    limit: int = 1500,
) -> dict:
    root = Path(bridge_root) if bridge_root is not None else resolve_bridge_root()
    tracked_statuses = tuple(dict.fromkeys((*ACTIVE_ORDER_STATUSES, *LOW_CONF_RECOVERY_STATUSES)))
    rows = (
        session.query(TradeOrder.id, TradeOrder.run_id, TradeOrder.status, TradeOrder.params)
        .filter(TradeOrder.status.in_(tracked_statuses))
        .order_by(TradeOrder.updated_at.desc(), TradeOrder.id.desc())
        .limit(max(int(limit or 0), 1))
        .all()
    )
    tracked_rows = [
        row
        for row in rows
        if _normalize_status(row.status) in ACTIVE_ORDER_STATUSES or _is_low_conf_missing(row.params)
    ]

    summary = {
        "orders_scanned": len(tracked_rows),
        "paths_ingested": 0,
        "paths_missing": 0,
        "errors": 0,
        "leader_paths_ingested": 0,
        "leader_paths_missing": 0,
        "leader_errors": 0,
    }
    ingested_paths: set[str] = set()

    # Leader bridge can backfill IB executions for short-lived direct executors.
    # Ingest it first so active orders can transition even if per-order files only have SUBMITTED.
    leader_events_path = root / "execution_events.jsonl"
    leader_key = str(leader_events_path)
    if leader_events_path.exists():
        try:
            ingest_execution_events(str(leader_events_path), session=session)
            ingested_paths.add(leader_key)
            summary["paths_ingested"] += 1
            summary["leader_paths_ingested"] += 1
        except Exception:
            summary["errors"] += 1
            summary["leader_errors"] += 1
    else:
        summary["paths_missing"] += 1
        summary["leader_paths_missing"] += 1

    for row in tracked_rows:
        events_path: Path | None = None
        if row.run_id:
            events_path = _resolve_run_events_path(session, int(row.run_id))
        else:
            events_path = root / f"direct_{int(row.id)}" / "execution_events.jsonl"

        if events_path is None:
            summary["paths_missing"] += 1
            continue

        key = str(events_path)
        if key in ingested_paths:
            continue

        if not events_path.exists():
            summary["paths_missing"] += 1
            continue

        try:
            ingest_execution_events(str(events_path), session=session)
            ingested_paths.add(key)
            summary["paths_ingested"] += 1
        except Exception:
            summary["errors"] += 1
            continue

    return summary


def reconcile_active_direct_orders(
    session,
    *,
    bridge_root: Path | None = None,
    mode: str | None = None,
    cancel_limit: int = 200,
) -> dict:
    root = Path(bridge_root) if bridge_root is not None else resolve_bridge_root()
    mode_value = str(mode or "").strip().lower() or "paper"
    open_orders_payload = read_open_orders(root)
    sync_summary = sync_trade_orders_from_open_orders(
        session,
        open_orders_payload,
        mode=mode_value,
        manual_only=True,
        include_new=True,
    )
    cancel_summary = reconcile_cancel_requested_orders(session, run_id=None, limit=max(1, int(cancel_limit)))
    return {
        "mode": mode_value,
        "sync": sync_summary,
        "cancel": cancel_summary,
    }


def reconcile_low_confidence_terminal_runs(
    session,
    *,
    bridge_root: Path | None = None,
    limit_runs: int = 20,
    order_scan_limit: int = 1000,
) -> dict:
    root = Path(bridge_root) if bridge_root is not None else resolve_bridge_root()
    positions_payload = read_positions(root)
    positions_stale = True
    if isinstance(positions_payload, dict):
        positions_stale = bool(positions_payload.get("stale") is True)
    summary = {
        "runs_scanned": 0,
        "runs_reconciled": 0,
        "orders_reconciled": 0,
        "positions_stale": positions_stale,
    }
    if not isinstance(positions_payload, dict) or positions_stale:
        return summary

    open_tags = _extract_open_tags(read_open_orders(root))
    rows = (
        session.query(TradeOrder.run_id, TradeOrder.status, TradeOrder.params)
        .filter(
            TradeOrder.run_id.isnot(None),
            TradeOrder.status.in_(LOW_CONF_RECOVERY_STATUSES),
        )
        .order_by(TradeOrder.updated_at.desc(), TradeOrder.id.desc())
        .limit(max(int(order_scan_limit or 0), 1))
        .all()
    )

    run_ids: list[int] = []
    seen: set[int] = set()
    for row in rows:
        if not _is_low_conf_missing(row.params):
            continue
        run_id = int(row.run_id)
        if run_id in seen:
            continue
        seen.add(run_id)
        run_ids.append(run_id)
        if len(run_ids) >= max(int(limit_runs or 0), 1):
            break

    for run_id in run_ids:
        run = session.get(TradeRun, int(run_id))
        if run is None:
            continue
        summary["runs_scanned"] += 1
        reconciled = reconcile_run_with_positions(session, run, positions_payload, open_tags=open_tags)
        reconciled_count = int(reconciled.get("reconciled") or 0)
        if reconciled_count <= 0:
            continue
        summary["runs_reconciled"] += 1
        summary["orders_reconciled"] += reconciled_count
        recompute_trade_run_completion_summary(session, run)

    return summary
