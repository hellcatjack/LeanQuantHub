from __future__ import annotations

import json
from pathlib import Path

from app.models import TradeOrder


def write_manual_order_intent(order: TradeOrder, *, output_dir: Path) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    quantity = float(order.quantity)
    side = str(order.side or "").strip().upper()
    if side == "SELL":
        quantity = -quantity
    payload = [
        {
            "order_intent_id": order.client_order_id,
            "symbol": order.symbol,
            "quantity": quantity,
            "weight": 0,
        }
    ]
    path = output_dir / f"order_intent_manual_{order.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
