from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import TradeOrder, TradeRun
from app.services.trade_orders import update_trade_order_status


_ACTIVE_ORDER_STATUSES = {"NEW", "SUBMITTED", "PARTIAL"}
_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED"}


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
        "checked": 0,
        "updated": 0,
        "skipped": 0,
        "skipped_no_tag": 0,
        "skipped_mode_mismatch": 0,
        "skipped_stale": 0,
    }
    if not isinstance(open_orders_payload, dict) or open_orders_payload.get("stale") is True:
        summary["skipped_stale"] = 1
        return summary

    open_tags = _extract_open_tags(open_orders_payload)
    if not open_tags:
        # Still reconcile: if there are no open tags, all active orders with a tag can be closed.
        open_tags = set()

    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.status.in_(sorted(_ACTIVE_ORDER_STATUSES)))
        .order_by(TradeOrder.id.asc())
        .all()
    )

    run_ids = {order.run_id for order in orders if order.run_id}
    run_modes: dict[int, str] = {}
    if run_ids:
        for run in session.query(TradeRun).filter(TradeRun.id.in_(sorted(run_ids))).all():
            run_modes[int(run.id)] = str(run.mode or "").strip().lower()

    event_time = _now_iso(now)
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

        if tag in open_tags:
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

    return summary

