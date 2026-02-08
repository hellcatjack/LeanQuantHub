from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.models import TradeFill, TradeOrder, TradeRun
from app.services.ib_orders import apply_fill_to_order
from app.services.trade_orders import update_trade_order_status
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_positions
from app.services.realized_pnl import compute_realized_pnl
from app.services.realized_pnl_baseline import ensure_positions_baseline


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
    commission: float | None
    realized_pnl: float | None
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


def _extract_order_id_from_tag(tag: str | None) -> int | None:
    text = str(tag or "").strip()
    if not text:
        return None
    if text.startswith("direct:"):
        raw = text[len("direct:") :]
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _parse_snapshot_tag(tag: str) -> tuple[int | None, str | None]:
    text = tag.strip()
    if not text.startswith("snapshot:"):
        return None, None
    parts = text.split(":")
    if len(parts) < 4:
        return None, None
    try:
        snapshot_id = int(parts[1])
    except ValueError:
        return None, None
    symbol = parts[3].strip().upper() if parts[3] else None
    return snapshot_id, symbol or None


def _resolve_snapshot_order_id(
    session,
    *,
    snapshot_id: int,
    symbol: str | None,
    side: str | None,
    tag: str | None,
) -> int | None:
    if session is None:
        return None
    query = session.query(TradeRun.id).filter(TradeRun.decision_snapshot_id == snapshot_id)
    run_ids = [row[0] for row in query.order_by(TradeRun.id.desc()).all()]
    if not run_ids:
        return None
    order_query = session.query(TradeOrder).filter(TradeOrder.run_id.in_(run_ids))
    if symbol:
        order_query = order_query.filter(TradeOrder.symbol == symbol)
    if side:
        order_query = order_query.filter(TradeOrder.side == side)
    candidates = order_query.order_by(TradeOrder.created_at.desc(), TradeOrder.id.desc()).all()
    for order in candidates:
        params = order.params or {}
        if tag and params.get("order_intent_id") == tag:
            return order.id
    if candidates:
        return candidates[0].id
    return None


def _resolve_order_id(event_path: Path, payload: dict, session=None) -> int | None:
    direct_id = _extract_direct_order_id(event_path)
    if direct_id is not None:
        return direct_id
    tag = payload.get("tag")
    direct_tag_id = _extract_order_id_from_tag(tag)
    if direct_tag_id is not None:
        return direct_tag_id
    snapshot_id, tag_symbol = _parse_snapshot_tag(str(tag or "").strip())
    if snapshot_id is None:
        return None
    symbol = (payload.get("symbol") or tag_symbol or "").strip().upper() or None
    side = _normalize_status(payload.get("direction"))
    return _resolve_snapshot_order_id(
        session,
        snapshot_id=snapshot_id,
        symbol=symbol,
        side=side if side else None,
        tag=tag,
    )


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


def _fill_exists(
    session,
    *,
    order_id: int,
    fill_qty: float,
    fill_price: float,
    event_time_iso: str,
) -> bool:
    fills = session.query(TradeFill).filter(TradeFill.order_id == order_id).all()
    for fill in fills:
        params = fill.params or {}
        if event_time_iso and params.get("event_time") == event_time_iso:
            return True
        if float(fill.fill_quantity) == float(fill_qty) and float(fill.fill_price) == float(fill_price):
            if event_time_iso:
                if _to_iso(fill.fill_time or fill.created_at) == event_time_iso:
                    return True
            else:
                return True
    return False


def _update_order_params(order: TradeOrder, payload: dict) -> None:
    params = dict(order.params or {})
    params.update(payload)
    order.params = params


def _append_warning(warnings: list[str], code: str) -> None:
    if code not in warnings:
        warnings.append(code)


def _ingest_lean_events(session, warnings: list[str]) -> None:
    bridge_root = resolve_bridge_root()
    if not bridge_root.exists():
        _append_warning(warnings, "lean_logs_missing")
        return

    seen_fill_keys: set[str] = set()

    for event_path in _iter_event_files(bridge_root):
        try:
            raw_lines = event_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            _append_warning(warnings, "lean_logs_read_error")
            continue
        for line in raw_lines:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                _append_warning(warnings, "lean_logs_parse_error")
                continue

            order_id = _resolve_order_id(event_path, payload, session=session)
            if order_id is None:
                _append_warning(warnings, "lean_event_missing_order")
                continue

            order = session.get(TradeOrder, order_id)
            if order is None:
                _append_warning(warnings, "lean_event_order_not_found")
                continue

            status = _normalize_status(payload.get("status"))
            filled = payload.get("filled")
            fill_qty = float(filled or 0.0)
            fill_price = payload.get("fill_price")
            fill_price_value = float(fill_price) if fill_price is not None else 0.0
            event_time = _parse_time(payload.get("time")) or datetime.utcnow().replace(tzinfo=timezone.utc)
            event_time_iso = _to_iso(event_time)
            event_tag = payload.get("tag")
            reason = payload.get("reason") or payload.get("message")

            if status in {"SUBMITTED", "NEW"}:
                if str(order.status or "").strip().upper() in {"NEW", "SUBMITTED"}:
                    try:
                        update_trade_order_status(
                            session,
                            order,
                            {
                                "status": "SUBMITTED",
                                "params": {
                                    "event_time": event_time_iso,
                                    "event_status": status,
                                    "event_source": "lean",
                                    "event_tag": event_tag,
                                },
                            },
                        )
                    except ValueError:
                        _append_warning(warnings, "lean_event_status_transition")
                continue

            if status in {"CANCELED", "CANCELLED"}:
                if str(order.status or "").strip().upper() not in {"CANCELED", "CANCELLED", "REJECTED"}:
                    try:
                        update_trade_order_status(
                            session,
                            order,
                            {
                                "status": "CANCELED",
                                "params": {
                                    "event_time": event_time_iso,
                                    "event_status": status,
                                    "event_source": "lean",
                                    "event_tag": event_tag,
                                },
                            },
                        )
                    except ValueError:
                        _append_warning(warnings, "lean_event_status_transition")
                continue

            if status in {"REJECTED", "INVALID"}:
                if str(order.status or "").strip().upper() != "REJECTED":
                    try:
                        update_payload = {
                            "status": "REJECTED",
                            "params": {
                                "event_time": event_time_iso,
                                "event_status": status,
                                "event_source": "lean",
                                "event_tag": event_tag,
                            },
                        }
                        if reason:
                            update_payload["params"]["reason"] = reason
                        update_trade_order_status(session, order, update_payload)
                    except ValueError:
                        _append_warning(warnings, "lean_event_status_transition")
                continue

            if status in {"FILLED", "PARTIALLYFILLED", "PARTIAL"} or fill_qty > 0:
                fill_key = f"{order_id}:{fill_qty}:{fill_price_value}:{event_time_iso}"
                if fill_key in seen_fill_keys:
                    continue
                seen_fill_keys.add(fill_key)
                if _fill_exists(
                    session,
                    order_id=order_id,
                    fill_qty=fill_qty,
                    fill_price=fill_price_value,
                    event_time_iso=event_time_iso,
                ):
                    if status == "FILLED" and str(order.status or "").strip().upper() != "FILLED":
                        filled_total = max(float(order.filled_quantity or 0.0), float(fill_qty or 0.0))
                        update_payload = {"status": "FILLED", "filled_quantity": filled_total}
                        if order.avg_fill_price is None and fill_price_value:
                            update_payload["avg_fill_price"] = float(fill_price_value)
                        try:
                            update_trade_order_status(session, order, update_payload)
                        except ValueError:
                            _append_warning(warnings, "lean_event_status_transition")
                    continue
                if str(order.status or "").strip().upper() == "FILLED":
                    _append_warning(warnings, "lean_event_duplicate_fill")
                    continue
                fill = apply_fill_to_order(
                    session,
                    order,
                    fill_qty=fill_qty,
                    fill_price=fill_price_value,
                    fill_time=_ensure_aware(event_time) or datetime.utcnow().replace(tzinfo=timezone.utc),
                )
                fill_params = dict(fill.params or {})
                fill_params.update(
                    {
                        "event_time": event_time_iso,
                        "event_source": "lean",
                        "event_tag": event_tag,
                    }
                )
                if reason:
                    fill_params["reason"] = reason
                fill.params = fill_params
                _update_order_params(
                    order,
                    {
                        "event_time": event_time_iso,
                        "event_status": status,
                        "event_source": "lean",
                        "event_tag": event_tag,
                    },
                )
                if status == "FILLED" and str(order.status or "").strip().upper() != "FILLED":
                    filled_total = max(float(order.filled_quantity or 0.0), float(fill_qty or 0.0))
                    update_payload = {"status": "FILLED", "filled_quantity": filled_total}
                    if order.avg_fill_price is None and fill_price_value:
                        update_payload["avg_fill_price"] = float(fill_price_value)
                    try:
                        update_trade_order_status(session, order, update_payload)
                    except ValueError:
                        _append_warning(warnings, "lean_event_status_transition")
                session.commit()



def list_trade_receipts(
    session,
    *,
    limit: int = 50,
    offset: int = 0,
    mode: str = "all",
) -> TradeReceiptPage:
    warnings: list[str] = []

    _ingest_lean_events(session, warnings)

    positions_payload = read_positions(resolve_bridge_root())
    baseline = ensure_positions_baseline(resolve_bridge_root(), positions_payload)
    realized = compute_realized_pnl(session, baseline)

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
                commission=None,
                realized_pnl=realized.order_totals.get(order.id, 0.0),
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
                commission=fill.commission,
                realized_pnl=realized.fill_totals.get(fill.id, 0.0),
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
        _append_warning(warnings, "lean_logs_missing")
    else:
        for event_path in _iter_event_files(bridge_root):
            try:
                raw_lines = event_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                _append_warning(warnings, "lean_logs_read_error")
                continue
            for line in raw_lines:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    _append_warning(warnings, "lean_logs_parse_error")
                    continue
                status = _normalize_status(payload.get("status"))
                filled = payload.get("filled")
                kind = _lean_kind(status, filled)
                event_time = _parse_time(payload.get("time"))
                order_id = _resolve_order_id(event_path, payload, session=session)
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
                realized_value = None
                if order_id is not None and kind == "order":
                    realized_value = realized.order_totals.get(order_id, 0.0)
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
                        commission=None,
                        realized_pnl=realized_value,
                        source="lean",
                    )
                )

    if mode == "orders":
        items = [item for item in items if item.kind == "order"]
    elif mode == "fills":
        items = [item for item in items if item.kind == "fill"]

    # Live-trade monitor expects newest order ids first (DESC) so receipts/fills correlate with the
    # orders table. Within the same order id, keep newest events first.
    items.sort(
        key=lambda item: (
            item.order_id if item.order_id is not None else -1,
            _ensure_aware(item.time) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    total = len(items)
    paged = items[offset : offset + limit]
    return TradeReceiptPage(items=paged, total=total, warnings=warnings)
