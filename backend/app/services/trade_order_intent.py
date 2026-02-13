from __future__ import annotations

import json
from pathlib import Path


def write_order_intent(
    session,
    *,
    snapshot_id: int,
    items: list[dict],
    output_dir: Path,
    run_id: int | None = None,
    order_type: str | None = None,
    limit_price_map: dict[str, float] | None = None,
    prime_price_map: dict[str, float] | None = None,
    outside_rth: bool | None = None,
    execution_session: str | None = None,
) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Snapshot-scoped intents are fine for offline/backtest flows, but trade execution must be
    # run-scoped to avoid overwriting in-flight runs that share the same decision snapshot.
    path = (
        output_dir / f"order_intent_run_{run_id}.json"
        if run_id
        else output_dir / f"order_intent_snapshot_{snapshot_id}.json"
    )
    payload = []
    intent_prefix = f"oi_{run_id}" if run_id else f"snapshot:{snapshot_id}"
    for idx, item in enumerate(items, start=1):
        symbol = (item.get("symbol") or "").strip().upper()
        existing_id = str(item.get("order_intent_id") or "").strip()
        if existing_id:
            intent_id = existing_id
        elif run_id:
            intent_id = f"{intent_prefix}_{idx}"
        else:
            intent_id = f"{intent_prefix}:{idx}:{symbol or 'NA'}"
        record = {
            "order_intent_id": intent_id,
            "symbol": symbol or item.get("symbol"),
            "quantity": item.get("quantity"),
            "weight": item.get("weight"),
            "snapshot_date": item.get("snapshot_date"),
            "rebalance_date": item.get("rebalance_date"),
        }
        if order_type:
            record["order_type"] = order_type
        if item.get("limit_price") is not None:
            record["limit_price"] = item.get("limit_price")
        if limit_price_map is not None and symbol:
            picked = limit_price_map.get(symbol)
            if picked is not None:
                record["limit_price"] = picked
        if prime_price_map is not None and symbol:
            prime = prime_price_map.get(symbol)
            if prime is not None:
                record["prime_price"] = prime
        if outside_rth is not None:
            record["outside_rth"] = bool(outside_rth)
        if execution_session:
            record["session"] = str(execution_session).strip().lower()
        payload.append(record)
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
    extended = {
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
    for idx, order in enumerate(orders):
        client_order_id = str(order.get("client_order_id") or f"oi_{run_id}_{idx}").strip()
        symbol = order.get("symbol")
        side = str(order.get("side") or "").strip().upper()
        quantity = float(order.get("quantity") or 0)
        signed_qty = -abs(quantity) if side == "SELL" else abs(quantity)
        params = order.get("params") if isinstance(order.get("params"), dict) else {}
        session = str(params.get("session") or params.get("execution_session") or params.get("trading_session") or "").strip().lower()
        allow_outside = params.get("allow_outside_rth")
        if allow_outside is None:
            allow_outside = params.get("outside_rth")
        if allow_outside is None:
            allow_outside = session in extended
        order_type = str(order.get("order_type") or "MKT").strip().upper() or "MKT"
        if order_type == "LIMIT":
            order_type = "LMT"
        limit_price = order.get("limit_price")
        payload.append(
            {
                "order_intent_id": client_order_id,
                "symbol": symbol,
                "quantity": signed_qty,
                "weight": 0,
                "order_type": order_type,
                "limit_price": limit_price,
                "outside_rth": bool(allow_outside),
                "session": session or None,
            }
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
