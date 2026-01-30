from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.audit_log import record_audit
from app.services.ib_settings import get_or_create_ib_settings, resolve_ib_api_mode
from app.services.trade_direct_intent import build_direct_intent_items
from app.services.trade_orders import create_trade_order
from app.services.ib_client_id_pool import ClientIdPoolExhausted, attach_lease_pid, lease_client_id
from app.services.lean_execution import build_execution_config, launch_execution_async
from app.services.lean_bridge_watchdog import refresh_bridge
from app.schemas import TradeDirectOrderOut


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

    order_type = str(payload.get("order_type") or "MKT").strip().upper()
    if order_type != "MKT":
        return False, "order_type_invalid"

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

    order_payload = {
        "client_order_id": payload.get("client_order_id"),
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "quantity": payload.get("quantity"),
        "order_type": payload.get("order_type") or "MKT",
        "limit_price": payload.get("limit_price"),
        "params": params,
    }

    result = create_trade_order(session, order_payload)
    session.commit()
    session.refresh(result.order)
    order = result.order

    intent_items = build_direct_intent_items(
        order_id=order.id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
    )
    intent_dir = Path(settings.artifact_root) / "order_intents"
    intent_dir.mkdir(parents=True, exist_ok=True)
    intent_path = intent_dir / f"order_intent_direct_{order.id}.json"
    intent_path.write_text(
        json.dumps(intent_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    output_dir = Path(settings.data_root or "/data/share/stock/data") / "lean_bridge" / f"direct_{order.id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        lease = lease_client_id(session, order_id=order.id, mode=mode, output_dir=str(output_dir))
    except ClientIdPoolExhausted as exc:
        raise ValueError("client_id_busy") from exc

    config = build_execution_config(
        intent_path=str(intent_path),
        brokerage="InteractiveBrokersBrokerage",
        project_id=project_id,
        mode=mode,
        client_id=lease.client_id,
        lean_bridge_output_dir=str(output_dir),
    )
    exec_dir = Path(settings.artifact_root) / "lean_execution"
    exec_dir.mkdir(parents=True, exist_ok=True)
    config_path = exec_dir / f"direct_order_{order.id}_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    pid = launch_execution_async(config_path=str(config_path))
    attach_lease_pid(session, lease_token=lease.lease_token or "", pid=pid)

    probe_path = exec_dir / f"direct_order_{order.id}.json"
    probe_path.write_text(
        json.dumps(
            {
                "order_id": order.id,
                "mode": mode,
                "intent_path": str(intent_path),
                "config_path": str(config_path),
                "submitted_at": datetime.utcnow().isoformat() + "Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record_audit(
        session,
        action="trade_order.direct_submit",
        resource_type="trade_order",
        resource_id=order.id,
        detail={
            "mode": mode,
            "intent_path": str(intent_path),
            "config_path": str(config_path),
        },
    )
    session.commit()

    bridge_status = refresh_bridge(session, mode=mode, reason="order_submit", force=False)
    refresh_result = bridge_status.get("last_refresh_result")

    return TradeDirectOrderOut(
        order_id=order.id,
        status=order.status or "NEW",
        execution_status="submitted_lean",
        intent_path=str(intent_path),
        config_path=str(config_path),
        bridge_status=bridge_status,
        refresh_result=refresh_result if isinstance(refresh_result, str) else None,
    )
