from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.models import TradeOrder

BRIDGE_ROOT = Path("/app/stocklean/artifacts/lean_bridge")
CACHE_ROOT = Path("/app/stocklean/data/lean_bridge/cache")


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_bridge_cache() -> None:
    account = _read_json(BRIDGE_ROOT / "account_summary.json")
    positions = _read_json(BRIDGE_ROOT / "positions.json")
    quotes = _read_json(BRIDGE_ROOT / "quotes.json")
    if account is not None:
        _write_json(CACHE_ROOT / "account_summary.json", account)
    if positions is not None:
        _write_json(CACHE_ROOT / "positions.json", positions)
    if quotes is not None:
        _write_json(CACHE_ROOT / "quotes.json", quotes)


def ingest_execution_events() -> None:
    path = BRIDGE_ROOT / "execution_events.jsonl"
    if not path.exists():
        return
    session = SessionLocal()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            order_id = event.get("order_id")
            if not order_id:
                continue
            order = session.get(TradeOrder, int(order_id))
            if not order:
                continue
            status = str(event.get("status") or "").upper()
            if status:
                order.status = status
            if event.get("avg_price") is not None:
                order.avg_fill_price = float(event.get("avg_price"))
            if event.get("filled") is not None:
                order.filled_quantity = float(event.get("filled"))
        session.commit()
    finally:
        session.close()
