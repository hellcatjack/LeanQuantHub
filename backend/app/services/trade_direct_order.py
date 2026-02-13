from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models import TradeOrder
from app.services.audit_log import record_audit
from app.services.ib_settings import get_or_create_ib_settings, resolve_ib_api_mode
from app.services.lean_bridge_commands import write_submit_order_command
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_bridge_status, read_quotes
from app.services.trade_direct_intent import build_direct_intent_items
from app.services.trade_price_seed import resolve_price_seed
from app.services.trade_orders import (
    create_trade_order,
    force_update_trade_order_status,
    update_trade_order_status,
)
from app.services.trade_order_types import is_limit_like, normalize_order_type, validate_order_type
from app.services.ib_client_id_pool import (
    ClientIdPoolExhausted,
    attach_lease_pid,
    lease_client_id,
    select_worker_client_id,
)
from app.services.lean_execution import build_execution_config, launch_execution_async
from app.services.lean_bridge_watchdog import refresh_bridge
from app.schemas import TradeDirectOrderOut

_DIRECT_RETRY_BASE_SECONDS = 20
_DIRECT_RETRY_MAX_SECONDS = 300
# Leader command submit->result roundtrip often takes >10s under IB/TWS load.
# Keep timeout above that window to avoid unnecessary short-lived fallback churn.
_DIRECT_LEADER_SUBMIT_TIMEOUT_SECONDS = 30

_LEADER_BRIDGE_READY_STATES = {"ok", "connected", "running", "degraded"}
_LEADER_COMMAND_STALE_SECONDS = 8
_LEADER_COMMAND_HISTORY_SECONDS = 300
_LEADER_COMMAND_REJECT_STATUSES = {
    "invalid",
    "place_failed",
    "not_connected",
    "expired",
    "parse_error",
    "symbol_invalid",
    "quantity_invalid",
    "unsupported_order_type",
    "limit_price_invalid",
}


_SESSION_EXTENDED = {
    "pre",
    "premarket",
    "pre_market",
    "post",
    "after",
    "afterhours",
    "after_hours",
    "night",
    "overnight",
}


def validate_direct_order_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in {"paper", "live"}:
        return False, "mode_invalid"

    symbol = str(payload.get("symbol") or "").strip()
    if not symbol:
        return False, "symbol_required"

    side = str(payload.get("side") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        return False, "side_invalid"

    try:
        order_type = validate_order_type(payload.get("order_type") or "MKT")
    except ValueError:
        return False, "order_type_invalid"

    if is_limit_like(order_type) and payload.get("limit_price") is not None:
        try:
            value = float(payload.get("limit_price"))
        except (TypeError, ValueError):
            return False, "limit_price_invalid"
        if value <= 0:
            return False, "limit_price_invalid"

    try:
        quantity = float(payload.get("quantity"))
    except (TypeError, ValueError):
        return False, "quantity_invalid"
    if quantity <= 0:
        return False, "quantity_invalid"

    if mode == "live":
        token = str(payload.get("live_confirm_token") or "").strip().upper()
        if token != "LIVE":
            return False, "live_confirm_required"

    return True, ""


def _select_worker(session, *, mode: str) -> int | None:
    return select_worker_client_id(session, mode=mode)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_retry_at(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compute_retry_delay(retry_count: int) -> int:
    if retry_count <= 1:
        return _DIRECT_RETRY_BASE_SECONDS
    delay = _DIRECT_RETRY_BASE_SECONDS * (2 ** (retry_count - 1))
    return int(min(delay, _DIRECT_RETRY_MAX_SECONDS))


def _update_retry_meta(order: TradeOrder, *, pending: bool, reason: str) -> dict:
    params = dict(order.params or {})
    meta = dict(params.get("direct_retry") or {})
    retry_count = int(meta.get("count") or 0) + 1
    now = _now_utc()
    delay = _compute_retry_delay(retry_count)
    next_at = now + timedelta(seconds=delay)
    meta.update(
        {
            "count": retry_count,
            "pending": pending,
            "last_reason": reason,
            "last_at": now.isoformat().replace("+00:00", "Z"),
            "next_retry_at": next_at.isoformat().replace("+00:00", "Z"),
        }
    )
    params["direct_retry"] = meta
    order.params = params
    return meta


def _resolve_submit_command_pending_age_seconds(order: TradeOrder, *, now: datetime) -> float | None:
    params = dict(order.params or {})
    submit_meta = params.get("submit_command")
    if not isinstance(submit_meta, dict) or not _as_bool(submit_meta.get("pending"), default=False):
        return None
    source = str(submit_meta.get("source") or "").strip().lower()
    if source and source != "leader_command":
        return None
    requested_at = _parse_retry_at(submit_meta.get("requested_at"))
    if requested_at is None:
        requested_at = _coerce_utc(getattr(order, "created_at", None)) or _coerce_utc(getattr(order, "updated_at", None))
    if requested_at is None:
        return None
    age = (now - requested_at).total_seconds()
    if age < 0:
        age = 0.0
    return float(age)


def _mark_submit_command_superseded(order: TradeOrder, *, reason: str, now: datetime) -> bool:
    params = dict(order.params or {})
    submit_meta = params.get("submit_command")
    if not isinstance(submit_meta, dict):
        return False
    if not _as_bool(submit_meta.get("pending"), default=False):
        return False
    processed_at = now.isoformat().replace("+00:00", "Z")
    merged_submit = dict(submit_meta)
    merged_submit["pending"] = False
    merged_submit["status"] = "superseded"
    merged_submit.setdefault("processed_at", processed_at)
    merged_submit["reason"] = reason
    merged_submit["superseded_by"] = "short_lived_fallback"
    params["submit_command"] = merged_submit
    params["event_source"] = "lean_command"
    params["sync_reason"] = "leader_submit_superseded"
    order.params = params
    return True


def _normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _normalize_session(value: object) -> str:
    text = str(value or "").strip().lower()
    return text


def _as_bool(value: Any, *, default: bool = False) -> bool:
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


def _infer_outside_rth(params: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(params, dict):
        return False, ""
    session = _normalize_session(params.get("session") or params.get("execution_session") or params.get("trading_session"))
    explicit = params.get("allow_outside_rth")
    if explicit is None:
        explicit = params.get("outside_rth")
    if explicit is True:
        return True, session
    if explicit is False:
        return False, session
    if session in _SESSION_EXTENDED:
        return True, session
    return False, session


def _pick_quote_limit_price(item: dict[str, Any], *, side: str, prefer_mid: bool = False) -> float | None:
    if not isinstance(item, dict):
        return None
    last = item.get("last")
    bid = item.get("bid")
    ask = item.get("ask")
    try:
        last_value = float(last) if last is not None else None
    except (TypeError, ValueError):
        last_value = None
    try:
        bid_value = float(bid) if bid is not None else None
    except (TypeError, ValueError):
        bid_value = None
    try:
        ask_value = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        ask_value = None

    if prefer_mid and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0

    # Prefer last trade if available. Otherwise prefer a reasonable point for the side.
    if last_value is not None and last_value > 0:
        return last_value

    if (not prefer_mid) and bid_value is not None and ask_value is not None and bid_value > 0 and ask_value > 0:
        return (bid_value + ask_value) / 2.0
    normalized_side = str(side or "").strip().upper()
    if normalized_side == "BUY":
        if ask_value is not None and ask_value > 0:
            return ask_value
        if bid_value is not None and bid_value > 0:
            return bid_value
    if normalized_side == "SELL":
        if bid_value is not None and bid_value > 0:
            return bid_value
        if ask_value is not None and ask_value > 0:
            return ask_value
    if bid_value is not None and bid_value > 0:
        return bid_value
    if ask_value is not None and ask_value > 0:
        return ask_value
    return None


def _resolve_limit_price_from_bridge(*, symbol: str, side: str, prefer_mid: bool = False) -> float | None:
    symbol_key = _normalize_symbol(symbol)
    if not symbol_key:
        return None
    quotes = read_quotes(resolve_bridge_root())
    items = quotes.get("items") if isinstance(quotes.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_symbol(item.get("symbol")) != symbol_key:
            continue
        price = _pick_quote_limit_price(item, side=side, prefer_mid=prefer_mid)
        if price is not None and price > 0:
            return float(price)
    return None


def _ensure_direct_intent(order: TradeOrder) -> Path:
    intent_dir = Path(settings.artifact_root) / "order_intents"
    intent_dir.mkdir(parents=True, exist_ok=True)
    intent_path = intent_dir / f"order_intent_direct_{order.id}.json"
    params = dict(order.params or {})
    allow_outside_rth, session = _infer_outside_rth(params)
    prime_price = resolve_price_seed(order.symbol)
    intent_items = build_direct_intent_items(
        order_id=order.id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        order_type=order.order_type or "MKT",
        limit_price=order.limit_price,
        prime_price=prime_price,
        allow_outside_rth=allow_outside_rth,
        session=session or None,
    )
    intent_path.write_text(
        json.dumps(intent_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return intent_path


def _should_use_leader_submit(order: TradeOrder) -> bool:
    params = dict(order.params or {})
    explicit = params.get("submit_via_leader")
    if explicit is not None:
        return _as_bool(explicit, default=False)
    # Default to leader command for direct/manual orders to keep submit/cancel/open-orders on
    # one long-lived IB client stream. This reduces short-lived executor tail-loss and speeds up
    # status convergence for batch liquidations.
    return True


def _is_bridge_ready_for_submit(bridge_root: Path) -> bool:
    try:
        status = read_bridge_status(bridge_root)
    except Exception:
        return False
    if not isinstance(status, dict):
        return False
    if status.get("stale") is True:
        return False
    state = str(status.get("status") or "").strip().lower()
    if state not in _LEADER_BRIDGE_READY_STATES:
        return False
    return _is_leader_command_channel_healthy(bridge_root)


def _is_leader_command_channel_healthy(
    bridge_root: Path,
    *,
    stale_seconds: int = _LEADER_COMMAND_STALE_SECONDS,
    history_seconds: int = _LEADER_COMMAND_HISTORY_SECONDS,
) -> bool:
    commands_dir = Path(bridge_root) / "commands"
    if not commands_dir.exists():
        return True
    now_ts = datetime.now(timezone.utc).timestamp()
    threshold = max(1, int(stale_seconds))
    recent_horizon = max(threshold + 1, int(history_seconds))
    try:
        pending_files = list(commands_dir.glob("submit_order_*.json"))
    except Exception:
        return False
    # Ignore historical leftovers (already expired/dead commands) and only treat recent stale
    # submit requests as unhealthy so old artifacts do not permanently disable leader mode.
    def _mtime(value: Path) -> float:
        try:
            return float(value.stat().st_mtime)
        except OSError:
            return 0.0

    for path in sorted(pending_files, key=_mtime, reverse=True)[:400]:
        try:
            age = now_ts - float(path.stat().st_mtime)
        except OSError:
            continue
        if age < 0:
            age = 0.0
        if age > float(recent_horizon):
            continue
        if age >= threshold:
            return False
    return True


def _submit_direct_execution_via_leader(
    session,
    *,
    order: TradeOrder,
    mode: str,
    intent_path: str,
    bridge_root: Path,
) -> TradeDirectOrderOut:
    params = dict(order.params or {})
    allow_outside_rth, _session_name = _infer_outside_rth(params)
    adaptive_priority = str(params.get("adaptive_priority") or "Normal").strip() or "Normal"
    broker_order_tag = str(order.client_order_id or "").strip() or f"direct:{order.id}"
    qty = float(order.quantity or 0.0)
    side = str(order.side or "").strip().upper()
    signed_qty = qty if side == "BUY" else -qty
    commands_dir = bridge_root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    cmd = write_submit_order_command(
        commands_dir,
        symbol=order.symbol,
        quantity=signed_qty,
        tag=broker_order_tag,
        order_type=order.order_type or "MKT",
        order_id=int(order.id),
        limit_price=order.limit_price,
        outside_rth=bool(allow_outside_rth),
        adaptive_priority=adaptive_priority,
        actor="trade_direct_order",
        reason=f"direct_order_{order.id}",
        expires_seconds=120,
    )

    submit_meta = {
        "pending": True,
        "command_id": cmd.command_id,
        "command_path": cmd.command_path,
        "requested_at": cmd.requested_at,
        "expires_at": cmd.expires_at,
        "source": "leader_command",
    }
    params["submit_command"] = submit_meta
    params["event_source"] = "lean_command"
    params["broker_order_tag"] = broker_order_tag
    params["event_tag"] = broker_order_tag
    order.params = params
    _update_retry_meta(order, pending=False, reason="submitted")
    session.commit()
    session.refresh(order)

    bridge_status = refresh_bridge(session, mode=mode, reason="order_submit", force=False)
    refresh_result = bridge_status.get("last_refresh_result")
    return TradeDirectOrderOut(
        order_id=order.id,
        status=order.status or "NEW",
        execution_status="submitted_leader",
        intent_path=intent_path,
        config_path=None,
        bridge_status=bridge_status,
        refresh_result=refresh_result if isinstance(refresh_result, str) else None,
    )


def reconcile_direct_submit_command_results(
    session,
    *,
    bridge_root: Path | None = None,
    limit: int = 400,
) -> dict[str, int]:
    root = Path(bridge_root) if bridge_root is not None else resolve_bridge_root()
    orders = (
        session.query(TradeOrder)
        .filter(TradeOrder.run_id.is_(None))
        .order_by(TradeOrder.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    summary = {"checked": 0, "updated": 0, "submitted": 0, "rejected": 0, "skipped": 0}

    for order in orders:
        params = dict(order.params or {})
        submit_meta = params.get("submit_command")
        if not isinstance(submit_meta, dict) or not _as_bool(submit_meta.get("pending"), default=False):
            continue
        summary["checked"] += 1
        command_id = str(submit_meta.get("command_id") or "").strip()
        if not command_id:
            summary["skipped"] += 1
            continue
        result_path = root / "command_results" / f"{command_id}.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary["skipped"] += 1
            continue
        if not isinstance(result, dict):
            summary["skipped"] += 1
            continue

        status = str(result.get("status") or "").strip().lower()
        merged_submit = dict(submit_meta)
        merged_submit["pending"] = False
        if status:
            merged_submit["status"] = status
        processed_at = result.get("processed_at")
        if processed_at:
            merged_submit["processed_at"] = processed_at

        payload_params = dict(params)
        payload_params["submit_command"] = merged_submit
        payload_params["event_source"] = "lean_command"
        payload_params["sync_reason"] = f"submit_command_{status or 'unknown'}"

        if status == "submitted":
            current = str(order.status or "").strip().upper()
            if current == "NEW":
                try:
                    update_trade_order_status(
                        session,
                        order,
                        {"status": "SUBMITTED", "params": payload_params},
                    )
                except ValueError:
                    force_update_trade_order_status(
                        session,
                        order,
                        {"status": "SUBMITTED", "params": payload_params},
                    )
            else:
                force_update_trade_order_status(
                    session,
                    order,
                    {"status": current or "SUBMITTED", "params": payload_params},
                )
            summary["updated"] += 1
            summary["submitted"] += 1
            continue

        if status in _LEADER_COMMAND_REJECT_STATUSES:
            reason = str(result.get("error") or status)
            try:
                update_trade_order_status(
                    session,
                    order,
                    {"status": "REJECTED", "params": {**payload_params, "reason": reason}},
                )
            except ValueError:
                force_update_trade_order_status(
                    session,
                    order,
                    {
                        "status": "REJECTED",
                        "params": {**payload_params, "reason": reason},
                        "rejected_reason": reason,
                    },
                )
            summary["updated"] += 1
            summary["rejected"] += 1
            continue

        current = str(order.status or "").strip().upper() or "NEW"
        force_update_trade_order_status(
            session,
            order,
            {"status": current, "params": payload_params},
        )
        summary["updated"] += 1

    return summary


def _launch_direct_execution(
    session,
    *,
    order: TradeOrder,
    mode: str,
    project_id: int,
    intent_path: str,
    output_dir: Path,
) -> TradeDirectOrderOut:
    lease = None
    client_id = _select_worker(session, mode=mode)
    if client_id is None:
        try:
            lease = lease_client_id(session, order_id=order.id, mode=mode, output_dir=str(output_dir))
            client_id = lease.client_id
        except ClientIdPoolExhausted:
            _update_retry_meta(order, pending=True, reason="client_id_busy")
            session.commit()
            return TradeDirectOrderOut(
                order_id=order.id,
                status=order.status or "NEW",
                execution_status="retry_pending",
                intent_path=intent_path,
            )

    config = build_execution_config(
        intent_path=intent_path,
        brokerage="InteractiveBrokersBrokerage",
        project_id=project_id,
        mode=mode,
        client_id=client_id,
        lean_bridge_output_dir=str(output_dir),
    )
    exec_dir = Path(settings.artifact_root) / "lean_execution"
    exec_dir.mkdir(parents=True, exist_ok=True)
    config_path = exec_dir / f"direct_order_{order.id}_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        pid = launch_execution_async(config_path=str(config_path))
    except Exception:
        _update_retry_meta(order, pending=True, reason="launch_failed")
        session.commit()
        return TradeDirectOrderOut(
            order_id=order.id,
            status=order.status or "NEW",
            execution_status="retry_pending",
            intent_path=intent_path,
            config_path=str(config_path),
        )
    if pid <= 0:
        _update_retry_meta(order, pending=True, reason="launch_failed")
        session.commit()
        return TradeDirectOrderOut(
            order_id=order.id,
            status=order.status or "NEW",
            execution_status="retry_pending",
            intent_path=intent_path,
            config_path=str(config_path),
        )

    if lease is not None:
        attach_lease_pid(session, lease_token=lease.lease_token or "", pid=pid)

    probe_path = exec_dir / f"direct_order_{order.id}.json"
    probe_path.write_text(
        json.dumps(
            {
                "order_id": order.id,
                "mode": mode,
                "intent_path": intent_path,
                "config_path": str(config_path),
                "submitted_at": datetime.utcnow().isoformat() + "Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _update_retry_meta(order, pending=False, reason="submitted")
    submitted_event_time = datetime.utcnow().isoformat() + "Z"
    broker_order_tag = f"direct:{order.id}"
    submit_params = {
        "event_source": "lean",
        "event_status": "SUBMITTED",
        "event_time": submitted_event_time,
        "sync_reason": "short_lived_submitted",
        "event_tag": broker_order_tag,
        "broker_order_tag": broker_order_tag,
    }
    try:
        update_trade_order_status(
            session,
            order,
            {"status": "SUBMITTED", "params": submit_params},
        )
    except ValueError:
        force_update_trade_order_status(
            session,
            order,
            {"status": "SUBMITTED", "params": submit_params},
        )

    bridge_status = refresh_bridge(session, mode=mode, reason="order_submit", force=False)
    refresh_result = bridge_status.get("last_refresh_result")

    return TradeDirectOrderOut(
        order_id=order.id,
        status=order.status or "SUBMITTED",
        execution_status="submitted_lean",
        intent_path=intent_path,
        config_path=str(config_path),
        bridge_status=bridge_status,
        refresh_result=refresh_result if isinstance(refresh_result, str) else None,
    )


def retry_direct_order(
    session,
    *,
    order_id: int,
    reason: str | None = None,
    force: bool = False,
    force_short_lived: bool = False,
) -> TradeDirectOrderOut:
    order = session.get(TradeOrder, order_id)
    if order is None:
        raise ValueError("order_not_found")
    status = str(order.status or "").strip().upper()
    if not force and status not in {"NEW", "REJECTED"}:
        raise ValueError("order_not_retryable")
    params = dict(order.params or {})
    mode = str(params.get("mode") or "paper").strip().lower() or "paper"
    project_id = int(params.get("project_id") or 0)
    intent_path = str(_ensure_direct_intent(order))
    output_dir = Path(settings.data_root or "/data/share/stock/data") / "lean_bridge" / f"direct_{order.id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    bridge_root = resolve_bridge_root()
    if force_short_lived:
        clock = _now_utc()
        superseded_reason = str(reason or "leader_submit_pending_timeout").strip() or "leader_submit_pending_timeout"
        if _mark_submit_command_superseded(order, reason=superseded_reason, now=clock):
            session.commit()
            session.refresh(order)
        return _launch_direct_execution(
            session,
            order=order,
            mode=mode,
            project_id=project_id,
            intent_path=intent_path,
            output_dir=output_dir,
        )
    if _should_use_leader_submit(order) and _is_bridge_ready_for_submit(bridge_root):
        return _submit_direct_execution_via_leader(
            session,
            order=order,
            mode=mode,
            intent_path=intent_path,
            bridge_root=bridge_root,
        )
    return _launch_direct_execution(
        session,
        order=order,
        mode=mode,
        project_id=project_id,
        intent_path=intent_path,
        output_dir=output_dir,
    )


def retry_pending_direct_orders(
    session,
    *,
    mode: str | None = None,
    now: datetime | None = None,
    limit: int = 200,
) -> dict[str, int]:
    mode_value = str(mode or "").strip().lower()
    clock = now or _now_utc()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    query = (
        session.query(TradeOrder)
        .filter(
            TradeOrder.run_id.is_(None),
            TradeOrder.status.in_(["NEW", "REJECTED"]),
        )
        .order_by(TradeOrder.created_at.asc())
        .limit(max(1, int(limit)))
    )
    orders = query.all()
    summary = {
        "scanned": 0,
        "scanned_leader_pending": 0,
        "retried": 0,
        "submitted": 0,
        "leader_timeout_retried": 0,
        "retry_pending": 0,
        "skipped_no_retry_meta": 0,
        "skipped_mode_mismatch": 0,
        "skipped_not_due": 0,
        "failed": 0,
    }
    for order in orders:
        params = dict(order.params or {})
        meta = dict(params.get("direct_retry") or {})
        retry_pending = bool(meta.get("pending"))
        leader_pending_age = _resolve_submit_command_pending_age_seconds(order, now=clock)
        leader_submit_timed_out = (
            str(order.status or "").strip().upper() == "NEW"
            and leader_pending_age is not None
            and leader_pending_age >= float(_DIRECT_LEADER_SUBMIT_TIMEOUT_SECONDS)
        )
        if not retry_pending and not leader_submit_timed_out:
            continue
        if leader_submit_timed_out and not retry_pending:
            summary["scanned_leader_pending"] += 1
        else:
            summary["scanned"] += 1
        order_mode = str(params.get("mode") or "paper").strip().lower() or "paper"
        if mode_value and order_mode != mode_value:
            summary["skipped_mode_mismatch"] += 1
            continue
        if retry_pending and not leader_submit_timed_out:
            due_at = _parse_retry_at(meta.get("next_retry_at"))
            if due_at is not None and due_at > clock:
                summary["skipped_not_due"] += 1
                continue
        force_short_lived = bool(leader_submit_timed_out)
        retry_reason = "leader_submit_pending_timeout" if force_short_lived else "auto_retry"
        try:
            result = retry_direct_order(
                session,
                order_id=int(order.id),
                reason=retry_reason,
                force=False,
                force_short_lived=force_short_lived,
            )
        except ValueError as exc:
            if str(exc) in {"order_not_found", "order_not_retryable"}:
                summary["skipped_no_retry_meta"] += 1
                continue
            _update_retry_meta(order, pending=True, reason="auto_retry_error")
            session.commit()
            summary["failed"] += 1
            continue
        except Exception:
            _update_retry_meta(order, pending=True, reason="auto_retry_error")
            session.commit()
            summary["failed"] += 1
            continue
        summary["retried"] += 1
        execution_status = str(result.execution_status or "").strip().lower()
        if execution_status in {"submitted_lean", "submitted_leader"}:
            summary["submitted"] += 1
            if force_short_lived:
                summary["leader_timeout_retried"] += 1
        elif execution_status == "retry_pending":
            summary["retry_pending"] += 1
    return summary


def submit_direct_order(session, payload: dict[str, Any]) -> TradeDirectOrderOut:
    ok, reason = validate_direct_order_payload(payload)
    if not ok:
        raise ValueError(reason)

    project_id = int(payload.get("project_id") or 0)
    mode = str(payload.get("mode") or "paper").strip().lower() or "paper"

    settings_row = get_or_create_ib_settings(session)
    api_mode = resolve_ib_api_mode(settings_row)
    if api_mode != "ib":
        raise ValueError("ib_api_mode_disabled")
    if not settings_row.host or not settings_row.port:
        raise ValueError("ib_settings_missing")

    params = dict(payload.get("params") or {})
    params.setdefault("source", "direct")
    params.setdefault("mode", mode)
    params.setdefault("project_id", project_id)

    order_type = validate_order_type(payload.get("order_type") or "MKT")
    limit_price = payload.get("limit_price")
    if order_type == "ADAPTIVE_LMT":
        limit_price = None
    elif is_limit_like(order_type) and limit_price is None:
        picked = _resolve_limit_price_from_bridge(
            symbol=str(payload.get("symbol") or ""),
            side=str(payload.get("side") or ""),
            prefer_mid=order_type == "PEG_MID",
        )
        if picked is None:
            raise ValueError("limit_price_unavailable")
        limit_price = float(picked)

    order_payload = {
        "client_order_id": payload.get("client_order_id"),
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "quantity": payload.get("quantity"),
        "order_type": order_type,
        "limit_price": limit_price,
        "params": params,
    }

    result = create_trade_order(session, order_payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    # Keep the default broker tag aligned with the submit command tag (`client_order_id`).
    # Short-lived fallback submissions can still switch to `direct:{order_id}` later.
    params = dict(order.params or {})
    broker_order_tag = str(order.client_order_id or "").strip() or f"direct:{order.id}"
    params.setdefault("broker_order_tag", broker_order_tag)
    params.setdefault("event_tag", broker_order_tag)
    order.params = params
    session.commit()
    session.refresh(order)

    intent_path = _ensure_direct_intent(order)
    output_dir = Path(settings.data_root or "/data/share/stock/data") / "lean_bridge" / f"direct_{order.id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    bridge_root = resolve_bridge_root()
    if _should_use_leader_submit(order) and _is_bridge_ready_for_submit(bridge_root):
        result = _submit_direct_execution_via_leader(
            session,
            order=order,
            mode=mode,
            intent_path=str(intent_path),
            bridge_root=bridge_root,
        )
    else:
        result = _launch_direct_execution(
            session,
            order=order,
            mode=mode,
            project_id=project_id,
            intent_path=str(intent_path),
            output_dir=output_dir,
        )

    record_audit(
        session,
        action="trade_order.direct_submit",
        resource_type="trade_order",
        resource_id=order.id,
        detail={
            "mode": mode,
            "intent_path": str(intent_path),
            "execution_status": result.execution_status,
        },
    )
    session.commit()

    return result
