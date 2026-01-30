from __future__ import annotations

import json
from pathlib import Path


def write_order_intent(session, *, snapshot_id: int, items: list[dict], output_dir: Path) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"order_intent_snapshot_{snapshot_id}.json"
    payload = []
    for idx, item in enumerate(items, start=1):
        symbol = (item.get("symbol") or "").strip().upper()
        intent_id = f"snapshot:{snapshot_id}:{idx}:{symbol or 'NA'}"
        payload.append(
            {
                "order_intent_id": intent_id,
                "symbol": symbol or item.get("symbol"),
                "weight": item.get("weight"),
                "snapshot_date": item.get("snapshot_date"),
                "rebalance_date": item.get("rebalance_date"),
            }
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def ensure_order_intent_ids(path: str, *, snapshot_id: int) -> bool:
    file_path = Path(path)
    if not file_path.exists():
        return False
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, list):
        return False
    updated = False
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        if item.get("order_intent_id"):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        item["order_intent_id"] = f"snapshot:{snapshot_id}:{idx}:{symbol or 'NA'}"
        updated = True
    if updated:
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated


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
