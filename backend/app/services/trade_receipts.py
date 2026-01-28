from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.models import TradeFill, TradeOrder
from app.services.lean_bridge_paths import resolve_bridge_root


@dataclass
class TradeReceipt:
    time: datetime | None
    kind: str
    order_id: int | None
    client_order_id: str | None
    symbol: str | None
    side: str | None
    quantity: float | None
    filled_quantity: float | None
    fill_price: float | None
    exec_id: str | None
    status: str | None
    source: str


@dataclass
class TradeReceiptPage:
    items: list[TradeReceipt]
    total: int
    warnings: list[str]


def _normalize_status(value: str | None) -> str:
    return str(value or "").strip().upper()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_iso(dt_value: datetime | None) -> str:
    if not dt_value:
        return ""
    dt_value = _ensure_aware(dt_value)
    return dt_value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_aware(dt_value: datetime | None) -> datetime | None:
    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=timezone.utc)
    return dt_value


def _extract_direct_order_id(event_path: Path) -> int | None:
    name = event_path.parent.name
    if not name.startswith("direct_"):
        return None
    raw = name[len("direct_") :]
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _lean_kind(status: str, filled: float | None) -> str:
    if filled and float(filled) > 0:
        return "fill"
    if status in {"FILLED", "PARTIALLYFILLED", "PARTIAL"}:
        return "fill"
    if status in {"SUBMITTED", "NEW"}:
        return "submit"
    if status in {"CANCELED", "CANCELLED"}:
        return "cancel"
    if status in {"INVALID", "REJECTED"}:
        return "reject"
    return "status"


def _iter_event_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return root.glob("**/execution_events.jsonl")


def list_trade_receipts(
    session,
    *,
    limit: int = 50,
    offset: int = 0,
    mode: str = "all",
) -> TradeReceiptPage:
    warnings: list[str] = []

    order_rows = session.query(TradeOrder).order_by(TradeOrder.created_at.desc()).all()
    order_map = {order.id: order for order in order_rows}
    items: list[TradeReceipt] = []

    for order in order_rows:
        items.append(
            TradeReceipt(
                time=_ensure_aware(order.created_at),
                kind="order",
                order_id=order.id,
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                filled_quantity=order.filled_quantity,
                fill_price=order.avg_fill_price,
                exec_id=None,
                status=order.status,
                source="db",
            )
        )

    fill_rows = (
        session.query(TradeFill)
        .join(TradeOrder, TradeFill.order_id == TradeOrder.id)
        .order_by(TradeFill.created_at.desc())
        .all()
    )

    db_fill_keys: set[tuple[int, float, float, str]] = set()
    for fill in fill_rows:
        order = order_map.get(fill.order_id)
        items.append(
            TradeReceipt(
                time=_ensure_aware(fill.fill_time or fill.created_at),
                kind="fill",
                order_id=fill.order_id,
                client_order_id=order.client_order_id if order else None,
                symbol=order.symbol if order else None,
                side=order.side if order else None,
                quantity=order.quantity if order else None,
                filled_quantity=fill.fill_quantity,
                fill_price=fill.fill_price,
                exec_id=fill.exec_id,
                status=order.status if order else None,
                source="db",
            )
        )
        db_fill_keys.add(
            (
                fill.order_id,
                float(fill.fill_quantity),
                float(fill.fill_price),
                _to_iso(fill.fill_time or fill.created_at),
            )
        )

    bridge_root = resolve_bridge_root()
    if not bridge_root.exists():
        warnings.append("lean_logs_missing")
    else:
        for event_path in _iter_event_files(bridge_root):
            try:
                raw_lines = event_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                warnings.append("lean_logs_read_error")
                continue
            for line in raw_lines:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    warnings.append("lean_logs_parse_error")
                    continue
                status = _normalize_status(payload.get("status"))
                filled = payload.get("filled")
                kind = _lean_kind(status, filled)
                event_time = _parse_time(payload.get("time"))
                order_id = _extract_direct_order_id(event_path)
                if kind == "fill" and order_id is not None:
                    key = (
                        order_id,
                        float(filled or 0.0),
                        float(payload.get("fill_price") or 0.0),
                        _to_iso(event_time),
                    )
                    if key in db_fill_keys:
                        continue
                direction = _normalize_status(payload.get("direction"))
                order = order_map.get(order_id) if order_id is not None else None
                items.append(
                    TradeReceipt(
                        time=_ensure_aware(event_time),
                        kind=kind,
                        order_id=order_id,
                        client_order_id=order.client_order_id if order else None,
                        symbol=payload.get("symbol") or (order.symbol if order else None),
                        side=direction or (order.side if order else None),
                        quantity=order.quantity if order else None,
                        filled_quantity=float(filled) if filled is not None else None,
                        fill_price=float(payload.get("fill_price") or 0.0)
                        if payload.get("fill_price") is not None
                        else None,
                        exec_id=None,
                        status=status or None,
                        source="lean",
                    )
                )

    if mode == "orders":
        items = [item for item in items if item.kind == "order"]
    elif mode == "fills":
        items = [item for item in items if item.kind == "fill"]

    items.sort(
        key=lambda item: _ensure_aware(item.time)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    total = len(items)
    paged = items[offset : offset + limit]
    return TradeReceiptPage(items=paged, total=total, warnings=warnings)
