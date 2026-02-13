from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import TradeOrder, TradeRun
from app.services.trade_orders import force_update_trade_order_status, update_trade_order_status


_ACTIVE_ORDER_STATUSES = {"SUBMITTED", "PARTIAL", "CANCEL_REQUESTED"}
_ACTIVE_ORDER_MISSING_GRACE_STATUSES = {"SUBMITTED", "PARTIAL"}
_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "SKIPPED"}
# Orders marked from low-confidence reconciliation may be recovered later when we observe
# concrete broker/Lean signals (open-orders presence or execution events).
_RECOVERABLE_TERMINAL_STATUSES = {"CANCELED", "CANCELLED", "SKIPPED"}
_NEW_ORDER_MISSING_CANCEL_GRACE_SECONDS = 60
# SUBMITTED/PARTIAL orders can briefly disappear from open-orders before fill events arrive.
# Use a longer grace to avoid transient false "CANCELED" states in UI.
_ACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS = 60
# Run-scoped strategy orders are more likely to be affected by short-lived executors and
# delayed execution-event ingestion. Keep a longer grace before inferring missing=>canceled.
_RUN_ACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS = 180
# After the missing-grace window, keep SUBMITTED/PARTIAL as unconfirmed for a while before
# low-confidence terminalization. This prevents orders from staying SUBMITTED indefinitely.
_ACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS = 300
_RUN_ACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS = 300
# When the run executor is no longer alive, execution events are unlikely to arrive from the
# run-scoped bridge path. Shorten missing-order convergence so run status does not stay
# SUBMITTED for several minutes after TWS has already completed the batch.
_RUN_INACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS = 60
_RUN_INACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS = 90
# Direct/manual orders are submitted via short-lived executors and often have no per-order
# execution-event tail after submit. Converge missing-from-open-orders faster to avoid
# lingering SUBMITTED statuses after TWS terminal states.
_DIRECT_ACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS = 30
_DIRECT_ACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS = 20
_DIRECT_ACTIVE_ORDER_MISSING_FAST_SOURCES = {"manual", "direct"}
# Leader-submit -> short-lived fallback can clear `submit_command.pending` before the fallback
# process actually submits to IB/TWS. During this grace window, do not infer NEW=>SKIPPED.
_SHORT_LIVED_FALLBACK_NEW_ORDER_MISSING_GRACE_SECONDS = 300
_CANCELED_OPEN_ORDER_STATUSES = {"CANCELED", "CANCELLED"}
_OPEN_ORDERS_MISSING_SINCE_KEY = "open_orders_missing_since"
_OPEN_ORDERS_MISSING_LAST_SEEN_KEY = "open_orders_missing_last_seen"
_OPEN_ORDERS_MISSING_UNCONFIRMED_KEY = "open_orders_missing_unconfirmed"


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


def _extract_open_items_by_tag(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    mapped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        tag = _normalize_tag(item.get("tag"))
        if not tag:
            continue
        mapped[tag] = item
    return mapped


def _normalize_open_order_status(value: object) -> str:
    return str(value or "").strip().upper()


def _as_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _is_submit_command_pending(params: dict[str, Any] | None) -> bool:
    if not isinstance(params, dict):
        return False
    submit_meta = params.get("submit_command")
    if not isinstance(submit_meta, dict):
        return False
    return _as_bool(submit_meta.get("pending"), default=False)


def _is_short_lived_fallback_submission_pending(
    params: dict[str, Any] | None,
    *,
    now: datetime,
) -> bool:
    if not isinstance(params, dict):
        return False
    submit_meta = params.get("submit_command")
    if not isinstance(submit_meta, dict):
        return False
    if _as_bool(submit_meta.get("pending"), default=False):
        return True

    source = str(submit_meta.get("source") or "").strip().lower()
    if source and source not in {"leader_command", "short_lived_fallback"}:
        return False

    superseded_by = str(submit_meta.get("superseded_by") or "").strip().lower()
    reason = str(submit_meta.get("reason") or "").strip().lower()
    status = str(submit_meta.get("status") or "").strip().lower()
    fallback_related = (
        superseded_by == "short_lived_fallback"
        or reason == "leader_submit_pending_timeout"
        or reason.endswith("pending_timeout")
    )
    if not fallback_related:
        return False
    if status and status not in {"superseded", "pending", "submitted"}:
        return False

    expires_at = _parse_iso_datetime(submit_meta.get("expires_at"))
    if expires_at is not None and now < expires_at:
        return True

    reference_dt = (
        _parse_iso_datetime(submit_meta.get("processed_at"))
        or _parse_iso_datetime(submit_meta.get("requested_at"))
        or _parse_iso_datetime(submit_meta.get("updated_at"))
    )
    if reference_dt is None:
        return True
    try:
        age_seconds = (now - reference_dt).total_seconds()
    except Exception:
        return True
    return age_seconds < _SHORT_LIVED_FALLBACK_NEW_ORDER_MISSING_GRACE_SECONDS


def _is_short_lived_fallback_related(params: dict[str, Any] | None) -> bool:
    if not isinstance(params, dict):
        return False
    submit_meta = params.get("submit_command")
    if not isinstance(submit_meta, dict):
        return False
    source = str(submit_meta.get("source") or "").strip().lower()
    if source and source not in {"leader_command", "short_lived_fallback"}:
        return False
    superseded_by = str(submit_meta.get("superseded_by") or "").strip().lower()
    reason = str(submit_meta.get("reason") or "").strip().lower()
    return superseded_by == "short_lived_fallback" or reason == "leader_submit_pending_timeout" or reason.endswith(
        "pending_timeout"
    )


def _is_client_scoped_master_snapshot(open_orders_payload: dict[str, Any]) -> bool:
    source_detail = str(open_orders_payload.get("source_detail") or "").strip().lower()
    if not source_detail.startswith("ib_open_orders"):
        return False
    for key in ("bridge_client_id", "client_id"):
        try:
            if int(open_orders_payload.get(key)) == 0:
                return True
        except (TypeError, ValueError):
            continue
    scope = str(open_orders_payload.get("open_orders_scope") or "").strip().lower()
    return scope in {"all", "master"}


def _now_iso(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_low_conf_missing_terminal(params: object) -> bool:
    if not isinstance(params, dict):
        return False
    return str(params.get("sync_reason") or "").strip() == "missing_from_open_orders"


def _is_direct_or_manual_order(order: TradeOrder) -> bool:
    if getattr(order, "run_id", None) is not None:
        return False
    params = dict(order.params or {}) if isinstance(order.params, dict) else {}
    source = str(params.get("source") or "").strip().lower()
    if source in _DIRECT_ACTIVE_ORDER_MISSING_FAST_SOURCES:
        return True
    event_tag = _normalize_tag(params.get("event_tag"))
    if event_tag.startswith("direct:"):
        return True
    client_order_id = str(getattr(order, "client_order_id", "") or "").strip().lower()
    return client_order_id.startswith("direct:")


def _resolve_order_tag_candidates(order: TradeOrder) -> list[str]:
    params = dict(order.params or {}) if isinstance(order.params, dict) else {}
    candidates = [
        params.get("broker_order_tag"),
        params.get("event_tag"),
        getattr(order, "client_order_id", None),
    ]
    resolved: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        tag = _normalize_tag(value)
        if not tag or tag in seen:
            continue
        resolved.append(tag)
        seen.add(tag)
    if _is_direct_or_manual_order(order):
        legacy_tag = f"direct:{int(order.id)}"
        if legacy_tag not in seen:
            resolved.append(legacy_tag)
    return resolved


def _persist_order_params(
    session,
    order: TradeOrder,
    *,
    updates: dict[str, Any] | None = None,
    remove_keys: set[str] | None = None,
) -> bool:
    merged = dict(order.params or {})
    changed = False
    for key in remove_keys or set():
        if key in merged:
            merged.pop(key, None)
            changed = True
    for key, value in (updates or {}).items():
        if merged.get(key) != value:
            merged[key] = value
            changed = True
    if not changed:
        return False
    order.params = merged
    order.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(order)
    return True


def sync_trade_orders_from_open_orders(
    session,
    open_orders_payload: dict[str, Any] | None,
    *,
    mode: str | None = None,
    run_id: int | None = None,
    manual_only: bool = False,
    include_new: bool = False,
    now: datetime | None = None,
    run_executor_active: bool | None = None,
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
        "updated_missing_to_skipped": 0,
        "updated_missing_unconfirmed_to_canceled": 0,
        "skipped": 0,
        "skipped_no_tag": 0,
        "skipped_empty_snapshot": 0,
        "skipped_no_overlap": 0,
        "skipped_mode_mismatch": 0,
        "skipped_partial_coverage": 0,
        "skipped_missing_grace": 0,
        "skipped_missing_unconfirmed": 0,
        "skipped_submit_pending": 0,
        "skipped_stale": 0,
    }
    if not isinstance(open_orders_payload, dict) or open_orders_payload.get("stale") is True:
        summary["skipped_stale"] = 1
        return summary

    source_detail = str(open_orders_payload.get("source_detail") or "").strip().lower()
    client_scoped = source_detail.startswith("ib_open_orders")
    client_scoped_master = _is_client_scoped_master_snapshot(open_orders_payload)

    open_items = open_orders_payload.get("items") if isinstance(open_orders_payload.get("items"), list) else []
    if not open_items:
        # Empty snapshots are only safe to infer from when we are reconciling a specific run using
        # that run's own execution client output (`ib_open_orders_empty` from run bridge root),
        # or when leader runs as IB master client-id (0), where client-scoped snapshots are
        # effectively account-wide.
        allow_empty = (
            (run_id is not None and source_detail == "ib_open_orders_empty")
            or (run_id is None and client_scoped_master)
        )
        if not allow_empty:
            summary["skipped_empty_snapshot"] = 1
            return summary
    open_by_tag = _extract_open_items_by_tag(open_orders_payload)
    open_tags = set(open_by_tag.keys())
    if not open_tags and open_items:
        # If IB returns open orders but none of them have tags, we can't safely reconcile by tag.
        # This can happen when older orders were placed without OrderRef propagation. Treat the
        # snapshot as unusable and avoid incorrectly cancelling active orders.
        summary["skipped_no_tag"] = summary.get("skipped_no_tag", 0) + 1
        return summary

    statuses = set(_ACTIVE_ORDER_STATUSES)
    if include_new:
        statuses.add("NEW")
    # Recovery: if we previously marked orders as canceled due to a stale/empty open-orders snapshot,
    # but IB still reports them as open now, we need to reconcile back to SUBMITTED.
    statuses.update(_RECOVERABLE_TERMINAL_STATUSES)
    query = session.query(TradeOrder).filter(TradeOrder.status.in_(sorted(statuses)))
    if run_id is not None:
        query = query.filter(TradeOrder.run_id == int(run_id))
    elif manual_only:
        query = query.filter(TradeOrder.run_id.is_(None))
    orders = query.order_by(TradeOrder.id.asc()).all()

    # IB "GetOpenOrders" is client-id scoped. When listing orders across all runs, we can't
    # safely infer broker-side cancels from missing tags because the snapshot may omit orders
    # submitted by other clients. Only apply "missing => canceled/skipped" when we have a
    # run-scoped snapshot or an all-open-orders view.
    infer_missing = True
    if client_scoped and run_id is None and not client_scoped_master:
        infer_missing = False

    # If the snapshot is client-scoped and it contains zero tags from this run, we can't safely
    # infer broker-side cancels for the run. This prevents false mass-cancels when the bridge
    # is connected under a different client-id.
    if run_id is not None and open_tags and client_scoped:
        run_known_tags: set[str] = set()
        for order in orders:
            tags = _resolve_order_tag_candidates(order)
            for tag in tags:
                run_known_tags.add(tag)
        if run_known_tags and run_known_tags.isdisjoint(open_tags):
            summary["skipped_no_overlap"] = 1
            return summary

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

        tag_candidates = _resolve_order_tag_candidates(order)
        if not tag_candidates:
            summary["skipped_no_tag"] += 1
            continue

        tag = tag_candidates[0]
        matched_tag = None
        for candidate in tag_candidates:
            if candidate in open_tags:
                matched_tag = candidate
                break

        current_status = str(order.status or "").strip().upper()

        if matched_tag is not None:
            tag = matched_tag
            if current_status in _ACTIVE_ORDER_MISSING_GRACE_STATUSES:
                _persist_order_params(
                    session,
                    order,
                    remove_keys={
                        _OPEN_ORDERS_MISSING_SINCE_KEY,
                        _OPEN_ORDERS_MISSING_LAST_SEEN_KEY,
                        _OPEN_ORDERS_MISSING_UNCONFIRMED_KEY,
                    },
                )
            open_item = open_by_tag.get(tag) or {}
            open_status = _normalize_open_order_status(open_item.get("status"))
            if open_status in _CANCELED_OPEN_ORDER_STATUSES:
                # Open-orders snapshots are low-confidence for canceled transitions and can be
                # out-of-order relative to execution events. Only confirm immediate broker-side
                # cancel when we are already in an explicit cancel flow. Direct/manual orders are
                # allowed to converge faster because they are not run-scoped and often lack a
                # reliable execution-event tail from short-lived executors.
                can_confirm_from_open_status = current_status == "CANCEL_REQUESTED" or (
                    _is_direct_or_manual_order(order) and current_status in {"NEW", "SUBMITTED", "PARTIAL"}
                )
                if not can_confirm_from_open_status:
                    summary["skipped"] += 1
                    continue
                if current_status not in _TERMINAL_ORDER_STATUSES:
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
                                    "sync_reason": "open_order_reports_canceled",
                                },
                            },
                        )
                    except ValueError:
                        summary["skipped"] += 1
                    else:
                        summary["updated"] += 1
                        summary["updated_missing_to_canceled"] += 1
                continue

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

            if current_status in _RECOVERABLE_TERMINAL_STATUSES and _is_low_conf_missing_terminal(order.params):
                try:
                    force_update_trade_order_status(
                        session,
                        order,
                        {
                            "status": "SUBMITTED",
                            "params": {
                                "event_source": "lean_open_orders",
                                "event_tag": tag,
                                "event_time": event_time,
                                "event_status": "SUBMITTED",
                                "sync_reason": "present_in_open_orders_recovered",
                            },
                        },
                    )
                except ValueError:
                    summary["skipped"] += 1
                else:
                    summary["updated"] += 1
                continue

            # Present and not NEW recovery: keep current state.
            continue

        # Tag absent from the open-orders snapshot.
        if current_status in _TERMINAL_ORDER_STATUSES:
            summary["skipped"] += 1
            continue
        if not infer_missing:
            summary["skipped_partial_coverage"] += 1
            continue

        if include_new and current_status == "NEW":
            if _is_submit_command_pending(order.params if isinstance(order.params, dict) else None):
                summary["skipped"] += 1
                summary["skipped_submit_pending"] += 1
                continue
            if _is_short_lived_fallback_submission_pending(
                order.params if isinstance(order.params, dict) else None,
                now=current_dt,
            ):
                summary["skipped"] += 1
                summary["skipped_submit_pending"] += 1
                continue
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

        if current_status in _ACTIVE_ORDER_MISSING_GRACE_STATUSES:
            params = dict(order.params or {})
            missing_since = _parse_iso_datetime(params.get(_OPEN_ORDERS_MISSING_SINCE_KEY))
            grace_seconds = _ACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS
            finalize_seconds = _ACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS
            if order.run_id is not None:
                grace_seconds = max(
                    _ACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS,
                    _RUN_ACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS,
                )
                finalize_seconds = max(
                    _ACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS,
                    _RUN_ACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS,
                )
                if run_executor_active is False:
                    grace_seconds = min(grace_seconds, _RUN_INACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS)
                    finalize_seconds = min(
                        finalize_seconds,
                        _RUN_INACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS,
                    )
                    if finalize_seconds < grace_seconds:
                        finalize_seconds = grace_seconds
            else:
                if _is_direct_or_manual_order(order):
                    grace_seconds = min(
                        grace_seconds,
                        _DIRECT_ACTIVE_ORDER_MISSING_CANCEL_GRACE_SECONDS,
                    )
                    finalize_seconds = min(
                        finalize_seconds,
                        _DIRECT_ACTIVE_ORDER_MISSING_UNCONFIRMED_FINALIZE_SECONDS,
                    )
                    if finalize_seconds < grace_seconds:
                        finalize_seconds = grace_seconds
            if missing_since is None:
                order_updated_at = getattr(order, "updated_at", None)
                order_age: float | None = None
                order_updated_iso = event_time
                if isinstance(order_updated_at, datetime):
                    updated_dt = order_updated_at
                    if updated_dt.tzinfo is None:
                        updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                    else:
                        updated_dt = updated_dt.astimezone(timezone.utc)
                    order_updated_iso = _now_iso(updated_dt)
                    try:
                        order_age = (current_dt - updated_dt).total_seconds()
                    except Exception:
                        order_age = None
                if order_age is not None and order_age >= finalize_seconds:
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
                                    _OPEN_ORDERS_MISSING_SINCE_KEY: order_updated_iso,
                                    _OPEN_ORDERS_MISSING_LAST_SEEN_KEY: event_time,
                                    _OPEN_ORDERS_MISSING_UNCONFIRMED_KEY: True,
                                    "open_orders_missing_age_seconds": round(float(order_age), 3),
                                },
                            },
                        )
                    except ValueError:
                        summary["skipped"] += 1
                    else:
                        summary["updated"] += 1
                        summary["updated_missing_to_canceled"] += 1
                        summary["updated_missing_unconfirmed_to_canceled"] += 1
                    continue
                _persist_order_params(
                    session,
                    order,
                    updates={_OPEN_ORDERS_MISSING_SINCE_KEY: event_time},
                )
                summary["skipped"] += 1
                summary["skipped_missing_grace"] += 1
                continue
            try:
                missing_age = (current_dt - missing_since).total_seconds()
            except Exception:
                missing_age = None
            if missing_age is None or missing_age < grace_seconds:
                summary["skipped"] += 1
                summary["skipped_missing_grace"] += 1
                continue

            if missing_age >= finalize_seconds:
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
                                _OPEN_ORDERS_MISSING_SINCE_KEY: params.get(_OPEN_ORDERS_MISSING_SINCE_KEY) or event_time,
                                _OPEN_ORDERS_MISSING_LAST_SEEN_KEY: event_time,
                                _OPEN_ORDERS_MISSING_UNCONFIRMED_KEY: True,
                                "open_orders_missing_age_seconds": round(float(missing_age), 3),
                            },
                        },
                    )
                except ValueError:
                    summary["skipped"] += 1
                else:
                    summary["updated"] += 1
                    summary["updated_missing_to_canceled"] += 1
                    summary["updated_missing_unconfirmed_to_canceled"] += 1
                continue

            # `open_orders` is a snapshot view and can temporarily miss working orders
            # while fills/cancels are still propagating. Keep active statuses unchanged
            # and wait for high-confidence execution events.
            unconfirmed_updates: dict[str, Any] = {}
            if params.get(_OPEN_ORDERS_MISSING_UNCONFIRMED_KEY) is not True:
                unconfirmed_updates[_OPEN_ORDERS_MISSING_UNCONFIRMED_KEY] = True
            # Avoid rewriting `last_seen` on every poll tick (causes high DB churn under
            # frequent order-page polling). Keep first observation for audit/debug only.
            if not params.get(_OPEN_ORDERS_MISSING_LAST_SEEN_KEY):
                unconfirmed_updates[_OPEN_ORDERS_MISSING_LAST_SEEN_KEY] = event_time
            if unconfirmed_updates:
                _persist_order_params(
                    session,
                    order,
                    updates=unconfirmed_updates,
                )
            summary["skipped"] += 1
            summary["skipped_missing_unconfirmed"] += 1
            continue

        if include_new and current_status == "NEW" and order.run_id is not None:
            order_params = order.params if isinstance(order.params, dict) else None
            fallback_expired = _is_short_lived_fallback_related(order_params) and not _is_short_lived_fallback_submission_pending(
                order_params,
                now=current_dt,
            )
            if fallback_expired:
                # Keep legacy convergence for timed-out fallback submits: these intents were
                # explicitly superseded and exceeded the fallback grace window.
                pass
            else:
                # Run-scoped NEW orders can be missing from open-orders temporarily while
                # the short-lived executor is still submitting and execution events are
                # delayed. Promote to SUBMITTED with low confidence and reuse the
                # active-order missing unconfirmed window instead of terminalizing.
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
                                "sync_reason": "missing_from_open_orders",
                                _OPEN_ORDERS_MISSING_SINCE_KEY: event_time,
                                _OPEN_ORDERS_MISSING_LAST_SEEN_KEY: event_time,
                                _OPEN_ORDERS_MISSING_UNCONFIRMED_KEY: True,
                            },
                        },
                    )
                except ValueError:
                    summary["skipped"] += 1
                    continue
                summary["updated"] += 1
                summary["updated_new_to_submitted"] += 1
                continue

        target_status = "CANCELED"
        target_event_status = "CANCELED"
        if include_new and current_status == "NEW":
            # Non-run-scoped NEW orders that never appear in open-orders are typically drafts
            # that were not submitted to brokerage.
            target_status = "SKIPPED"
            target_event_status = "SKIPPED"

        try:
            update_trade_order_status(
                session,
                order,
                {
                    "status": target_status,
                    "params": {
                        "event_source": "lean_open_orders",
                        "event_tag": tag,
                        "event_time": event_time,
                        "event_status": target_event_status,
                        "sync_reason": "missing_from_open_orders",
                    },
                },
            )
        except ValueError:
            summary["skipped"] += 1
            continue

        summary["updated"] += 1
        if target_status == "SKIPPED":
            summary["updated_missing_to_skipped"] += 1
        else:
            summary["updated_missing_to_canceled"] += 1

    return summary
