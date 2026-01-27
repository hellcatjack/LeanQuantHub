from __future__ import annotations

import json
from pathlib import Path


def write_order_intent(session, *, snapshot_id: int, items: list[dict], output_dir: Path) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"order_intent_snapshot_{snapshot_id}.json"
    payload = []
    for item in items:
        payload.append(
            {
                "symbol": item.get("symbol"),
                "weight": item.get("weight"),
                "snapshot_date": item.get("snapshot_date"),
                "rebalance_date": item.get("rebalance_date"),
            }
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def write_order_intent_manual(*, run_id: int, orders: list[dict], output_dir: Path) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"order_intent_manual_run_{run_id}.json"
    payload = []
    for idx, order in enumerate(orders):
        client_order_id = str(order.get("client_order_id") or f"oi_{run_id}_{idx}").strip()
        symbol = order.get("symbol")
        side = str(order.get("side") or "").strip().upper()
        quantity = float(order.get("quantity") or 0)
        signed_qty = -abs(quantity) if side == "SELL" else abs(quantity)
        payload.append(
            {
                "order_intent_id": client_order_id,
                "symbol": symbol,
                "quantity": signed_qty,
                "weight": 0,
            }
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
