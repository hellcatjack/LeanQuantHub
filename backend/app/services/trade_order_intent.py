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
) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"order_intent_snapshot_{snapshot_id}.json"
    payload = []
    intent_prefix = f"oi_{run_id or snapshot_id}"
    for idx, item in enumerate(items, start=1):
        payload.append(
            {
                "order_intent_id": f"{intent_prefix}_{idx}",
                "symbol": item.get("symbol"),
                "weight": item.get("weight"),
                "snapshot_date": item.get("snapshot_date"),
                "rebalance_date": item.get("rebalance_date"),
            }
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
