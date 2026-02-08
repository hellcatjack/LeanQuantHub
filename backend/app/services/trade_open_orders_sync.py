from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import TradeOrder, TradeRun
from app.services.trade_orders import update_trade_order_status


_ACTIVE_ORDER_STATUSES = {"SUBMITTED", "PARTIAL"}
_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED"}
_NEW_ORDER_MISSING_CANCEL_GRACE_SECONDS = 60


def _normalize_tag(value: object) -> str:
    return str(value or "").strip()


def _extract_open_tags(payload: dict[str, Any]) -> set[str]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    tags: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = _normalize_tag(item.get("tag"))
        if tag:
            tags.add(tag)
    return tags


def _now_iso(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sync_trade_orders_from_open_orders(
    session,
    open_orders_payload: dict[str, Any] | None,
    *,
    mode: str | None = None,
    run_id: int | None = None,
    manual_only: bool = False,
    include_new: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile TradeOrder.status with IB open orders snapshot from Lean bridge.

    If an order is ACTIVE in DB but its tag is absent from the open-orders snapshot,
    we treat it as canceled (covers manual cancellations from TWS when execution client
    is no longer connected).
    """
    mode_value = str(mode or "").strip().lower()
    summary: dict[str, Any] = {
        "mode": mode_value or None,
        "run_id": int(run_id) if run_id is not None else None,
        "manual_only": bool(manual_only),
        "include_new": bool(include_new),
        "checked": 0,
        "updated": 0,
        "updated_new_to_submitted": 0,
        "updated_missing_to_canceled": 0,
        "skipped": 0,
        "skipped_no_tag": 0,
        "skipped_mode_mismatch": 0,
        "skipped_stale": 0,
    }
    if not isinstance(open_orders_payload, dict) or open_orders_payload.get("stale") is True:
        summary["skipped_stale"] = 1
        return summary

    open_tags = _extract_open_tags(open_orders_payload)
    open_items = open_orders_payload.get("items") if isinstance(open_orders_payload.get("items"), list) else []
    if not open_tags and open_items:
        # If IB returns open orders but none of them have tags, we can't safely reconcile by tag.
        # This can happen when older orders were placed without OrderRef propagation. Treat the
        # snapshot as unusable and avoid incorrectly cancelling active orders.
        summary["skipped_no_tag"] = summary.get("skipped_no_tag", 0) + 1
        return summary

    statuses = set(_ACTIVE_ORDER_STATUSES)
    if include_new:
        statuses.add("NEW")
    query = session.query(TradeOrder).filter(TradeOrder.status.in_(sorted(statuses)))
    if run_id is not None:
        query = query.filter(TradeOrder.run_id == int(run_id))
    elif manual_only:
        query = query.filter(TradeOrder.run_id.is_(None))
    orders = query.order_by(TradeOrder.id.asc()).all()

    run_ids = {order.run_id for order in orders if order.run_id}
    run_modes: dict[int, str] = {}
    if run_ids:
        for run in session.query(TradeRun).filter(TradeRun.id.in_(sorted(run_ids))).all():
            run_modes[int(run.id)] = str(run.mode or "").strip().lower()

    current_dt = now or datetime.now(timezone.utc)
    if current_dt.tzinfo is None:
        current_dt = current_dt.replace(tzinfo=timezone.utc)
    event_time = _now_iso(current_dt)
    for order in orders:
        summary["checked"] += 1

        order_mode: str | None = None
        if order.run_id and order.run_id in run_modes:
            order_mode = run_modes.get(order.run_id) or None
        elif isinstance(order.params, dict):
            order_mode = str(order.params.get("mode") or "").strip().lower() or None

        if mode_value and order_mode and order_mode != mode_value:
            summary["skipped_mode_mismatch"] += 1
            continue

        if str(order.status or "").strip().upper() in _TERMINAL_ORDER_STATUSES:
            summary["skipped"] += 1
            continue

        tag = None
        if isinstance(order.params, dict):
            tag = _normalize_tag(order.params.get("event_tag"))
        if not tag:
            client_order_id = str(order.client_order_id or "").strip()
            if client_order_id.startswith("oi_") or client_order_id.startswith("direct:"):
                tag = client_order_id
        if not tag:
            summary["skipped_no_tag"] += 1
            continue

        current_status = str(order.status or "").strip().upper()
        if tag in open_tags:
            current_status = str(order.status or "").strip().upper()
            if include_new and current_status == "NEW":
                try:
                    update_trade_order_status(
                        session,
                        order,
                        {
                            "status": "SUBMITTED",
                            "params": {
                                "event_source": "lean_open_orders",
                                "event_tag": tag,
                                "event_time": event_time,
                                "event_status": "SUBMITTED",
                                "sync_reason": "present_in_open_orders",
                            },
                        },
                    )
                except ValueError:
                    summary["skipped"] += 1
                else:
                    summary["updated"] += 1
                    summary["updated_new_to_submitted"] += 1
            continue

        if include_new and current_status == "NEW":
            created_at = getattr(order, "created_at", None)
            if created_at:
                created_dt = created_at
                if getattr(created_dt, "tzinfo", None) is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                try:
                    age_seconds = (current_dt - created_dt).total_seconds()
                except Exception:
                    age_seconds = None
                if age_seconds is not None and age_seconds < _NEW_ORDER_MISSING_CANCEL_GRACE_SECONDS:
                    # Avoid prematurely cancelling newly-created orders when the open-orders snapshot
                    # hasn't caught up with IB/TWS yet (common right after submission).
                    summary["skipped"] += 1
                    continue

        try:
            update_trade_order_status(
                session,
                order,
                {
                    "status": "CANCELED",
                    "params": {
                        "event_source": "lean_open_orders",
                        "event_tag": tag,
                        "event_time": event_time,
                        "event_status": "CANCELED",
                        "sync_reason": "missing_from_open_orders",
                    },
                },
            )
        except ValueError:
            summary["skipped"] += 1
            continue

        summary["updated"] += 1
        summary["updated_missing_to_canceled"] += 1

    return summary
