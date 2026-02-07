from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from app.core.config import settings
from app.models import TradeOrder
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_execution import build_execution_config, launch_execution_async

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")


def write_manual_order_intent(order: TradeOrder, *, output_dir: Path) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    quantity = float(order.quantity)
    side = str(order.side or "").strip().upper()
    if side == "SELL":
        quantity = -quantity
    params = dict(order.params or {})
    session = str(params.get("session") or params.get("execution_session") or params.get("trading_session") or "").strip().lower()
    allow_outside = params.get("allow_outside_rth")
    if allow_outside is None:
        allow_outside = params.get("outside_rth")
    if allow_outside is None:
        allow_outside = session in {
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
    order_type = str(order.order_type or "MKT").strip().upper() or "MKT"
    if order_type == "LIMIT":
        order_type = "LMT"
    limit_price = order.limit_price
    payload = [
        {
            "order_intent_id": order.client_order_id,
            "symbol": order.symbol,
            "quantity": quantity,
            "weight": 0,
            "order_type": order_type,
            "limit_price": limit_price,
            "outside_rth": bool(allow_outside),
            "session": session or None,
        }
    ]
    path = output_dir / f"order_intent_manual_{order.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def execute_manual_order(
    session,
    order: TradeOrder,
    *,
    project_id: int,
    mode: str,
) -> str:
    intent_path = write_manual_order_intent(order, output_dir=ARTIFACT_ROOT / "order_intents")
    bridge_root = resolve_bridge_root()
    output_dir = bridge_root / f"direct_{order.id}"
    config = build_execution_config(
        intent_path=intent_path,
        brokerage="InteractiveBrokersBrokerage",
        project_id=project_id,
        mode=mode,
        lean_bridge_output_dir=str(output_dir),
    )
    config_dir = ARTIFACT_ROOT / "lean_execution"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"manual_order_{order.id}.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    pid = launch_execution_async(config_path=str(config_path))

    params = dict(order.params or {})
    params["manual_execution"] = {
        "intent_path": intent_path,
        "config_path": str(config_path),
        "pid": pid,
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "project_id": project_id,
        "mode": mode,
    }
    order.params = params
    session.commit()
    return str(config_path)
