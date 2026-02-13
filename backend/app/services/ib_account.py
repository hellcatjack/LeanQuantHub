from __future__ import annotations

import copy
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from time import monotonic
from typing import Any

from app.core.config import settings
from app.models import TradeOrder, TradeRun
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.ib_settings import ensure_ib_client_id, get_or_create_ib_settings
from app.services.lean_bridge_watchdog import ensure_lean_bridge_live
from app.services.lean_bridge_reader import read_account_summary, read_positions, read_quotes
from app.services.realized_pnl import compute_realized_pnl
from app.services.realized_pnl_baseline import ensure_positions_baseline


CORE_TAGS = (
    "NetLiquidation",
    "TotalCashValue",
    "AvailableFunds",
    "CashBalance",
)

CACHE_ROOT: Path | None = None
_VALID_HOLDINGS_SOURCE_DETAILS = {"ib_holdings", "ib_holdings_empty"}
_DIRECT_FILL_STATUSES = ("FILLED", "PARTIAL")
_OVERLAY_RECENT_DIRECT_FILL_MAX_AGE_SECONDS = 300
_INFER_RECENT_DIRECT_FILL_MAX_AGE_SECONDS = 1800
_OVERLAY_TERMINAL_FILL_GRACE_SECONDS = 60
_OVERLAY_ACTIVE_ORDER_STATUSES = {
    "NEW",
    "SUBMITTED",
    "PARTIAL",
    "CANCEL_REQUESTED",
}
_ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS = max(
    float(getattr(settings, "ib_account_positions_response_cache_ttl_seconds", 1.0) or 1.0),
    0.0,
)
_ACCOUNT_POSITIONS_RESPONSE_CACHE_MAX_ENTRIES = max(
    int(getattr(settings, "ib_account_positions_response_cache_max_entries", 32) or 32),
    1,
)
_ACCOUNT_POSITIONS_RESPONSE_INFLIGHT_WAIT_SECONDS = max(
    float(getattr(settings, "ib_account_positions_response_inflight_wait_seconds", 0.35) or 0.35),
    0.05,
)
_ACCOUNT_POSITIONS_RESPONSE_INFLIGHT_STALE_SECONDS = max(
    float(getattr(settings, "ib_account_positions_response_inflight_stale_seconds", 2.0) or 2.0),
    0.1,
)
_SYMBOL_LATEST_GUARD_STATUSES = (
    "NEW",
    "SUBMITTED",
    "PARTIAL",
    "FILLED",
    "CANCEL_REQUESTED",
    "CANCELED",
    "CANCELLED",
    "REJECTED",
    "SKIPPED",
    "INVALID",
)
_account_positions_response_cache_lock = Lock()
_account_positions_response_cache: dict[tuple[str], tuple[float, dict[str, object]]] = {}
_account_positions_response_inflight: dict[tuple[str], tuple[Event, float]] = {}


def _account_positions_cache_key(*, mode: str) -> tuple[str]:
    mode_key = str(mode or "").strip().lower()
    if not mode_key:
        mode_key = "paper"
    return (mode_key,)


def _prune_account_positions_response_cache(*, now_mono: float) -> None:
    expired_keys = [
        key
        for key, (expires_at_mono, _payload) in _account_positions_response_cache.items()
        if expires_at_mono <= now_mono
    ]
    for key in expired_keys:
        _account_positions_response_cache.pop(key, None)
    overflow = len(_account_positions_response_cache) - _ACCOUNT_POSITIONS_RESPONSE_CACHE_MAX_ENTRIES
    if overflow > 0:
        eviction_keys = sorted(
            _account_positions_response_cache.items(),
            key=lambda item: item[1][0],
        )[:overflow]
        for key, _entry in eviction_keys:
            _account_positions_response_cache.pop(key, None)


def _get_account_positions_response_cache(key: tuple[str]) -> dict[str, object] | None:
    if _ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS <= 0:
        return None
    now_mono = monotonic()
    with _account_positions_response_cache_lock:
        _prune_account_positions_response_cache(now_mono=now_mono)
        entry = _account_positions_response_cache.get(key)
        if entry is None:
            return None
        expires_at_mono, payload = entry
        if expires_at_mono <= now_mono:
            _account_positions_response_cache.pop(key, None)
            return None
        return copy.deepcopy(payload)


def _store_account_positions_response_cache(key: tuple[str], payload: dict[str, object]) -> None:
    if _ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS <= 0:
        return
    now_mono = monotonic()
    with _account_positions_response_cache_lock:
        _account_positions_response_cache[key] = (
            now_mono + _ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS,
            copy.deepcopy(payload),
        )
        _prune_account_positions_response_cache(now_mono=now_mono)


def _acquire_account_positions_response_inflight(
    key: tuple[str],
    *,
    allow_steal_stale: bool = False,
) -> tuple[bool, Event]:
    now_mono = monotonic()
    with _account_positions_response_cache_lock:
        entry = _account_positions_response_inflight.get(key)
        if entry is not None:
            event, started_mono = entry
            if (
                allow_steal_stale
                and (now_mono - float(started_mono))
                >= _ACCOUNT_POSITIONS_RESPONSE_INFLIGHT_STALE_SECONDS
            ):
                replacement = Event()
                _account_positions_response_inflight[key] = (replacement, now_mono)
                # Wake current waiters so they can retry against the replacement owner.
                event.set()
                return True, replacement
            return False, event
        created = Event()
        _account_positions_response_inflight[key] = (created, now_mono)
        return True, created


def _release_account_positions_response_inflight(key: tuple[str], event: Event) -> None:
    with _account_positions_response_cache_lock:
        entry = _account_positions_response_inflight.get(key)
        current = entry[0] if isinstance(entry, tuple) else None
        if current is event:
            _account_positions_response_inflight.pop(key, None)
        event.set()


def _clear_account_positions_response_cache() -> None:
    with _account_positions_response_cache_lock:
        _account_positions_response_cache.clear()
        _account_positions_response_inflight.clear()


def _build_account_positions_fast_fallback(*, mode: str) -> dict[str, object]:
    payload = read_positions(_resolve_bridge_root())
    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
    stale = bool(payload.get("stale", True))
    source_detail = str(payload.get("source_detail") or "").strip() or "ib_holdings_fast_fallback"
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    items: list[dict[str, object]] = []
    if source_detail in _VALID_HOLDINGS_SOURCE_DETAILS:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            if "position" not in normalized and "quantity" in normalized:
                normalized["position"] = normalized.get("quantity")
            items.append(normalized)
    else:
        stale = True
    return {
        "items": items,
        "refreshed_at": refreshed_at,
        "stale": stale,
        "source_detail": source_detail,
        "mode": mode,
    }


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def _read_cached_summary() -> dict[str, object] | None:
    if CACHE_ROOT is None:
        return None
    path = Path(CACHE_ROOT) / "account_summary.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    items = data.get("items") if "items" in data else data
    return {
        "items": items,
        "refreshed_at": data.get("updated_at") or data.get("refreshed_at"),
        "source": "cache",
        "stale": bool(data.get("stale", False)),
    }


def _normalize_items(raw_items: Any) -> dict[str, object]:
    if isinstance(raw_items, dict):
        return raw_items
    items: dict[str, object] = {}
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            items[str(name)] = item.get("value")
    return items


def _filter_summary(raw: Any, *, full: bool) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    if full:
        return dict(raw)
    return {key: value for key, value in raw.items() if key in CORE_TAGS}


def build_account_summary_tags(*, full: bool) -> str:
    if full:
        return "All"
    return ",".join(CORE_TAGS)


def resolve_ib_account_settings(session):
    return get_or_create_ib_settings(session)


def iter_account_client_ids(base: int, *, attempts: int = 3):
    base_id = int(base)
    count = max(int(attempts), 0)
    for offset in range(count):
        yield base_id + offset


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if "." in normalized:
        head, tail = normalized.split(".", 1)
        tz = ""
        tz_index = None
        for sep in ("+", "-"):
            idx = tail.find(sep)
            if idx > 0:
                tz_index = idx
                break
        if tz_index is not None:
            frac = tail[:tz_index]
            tz = tail[tz_index:]
        else:
            frac = tail
        if len(frac) > 6:
            frac = frac[:6]
        normalized = f"{head}.{frac}{tz}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_position_quantity(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if abs(parsed) <= 1e-9:
        return 0.0
    return float(parsed)


def _order_updated_at_utc(order: TradeOrder) -> datetime | None:
    params = order.params if isinstance(getattr(order, "params", None), dict) else {}
    event_time = _parse_timestamp(params.get("event_time")) if params else None
    if event_time is not None:
        return event_time
    updated_at = getattr(order, "updated_at", None)
    if updated_at is None:
        return None
    if updated_at.tzinfo is None:
        return updated_at.replace(tzinfo=timezone.utc)
    return updated_at.astimezone(timezone.utc)


def _normalize_order_status(value: object) -> str:
    return str(value or "").strip().upper()


def _order_is_recent(
    order: TradeOrder,
    *,
    reference_time: datetime,
    max_age_seconds: int,
) -> bool:
    if max_age_seconds <= 0:
        return True
    order_dt = _order_updated_at_utc(order)
    if order_dt is None:
        return False
    try:
        age_seconds = (reference_time - order_dt).total_seconds()
    except Exception:
        return False
    if age_seconds <= 0:
        return True
    return age_seconds <= float(max_age_seconds)


def _order_identity(order: TradeOrder) -> int:
    try:
        return int(getattr(order, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_order_newer(candidate: TradeOrder, existing: TradeOrder) -> bool:
    candidate_dt = _order_updated_at_utc(candidate)
    existing_dt = _order_updated_at_utc(existing)
    if candidate_dt and existing_dt:
        if candidate_dt > existing_dt:
            return True
        if candidate_dt < existing_dt:
            return False
    elif candidate_dt and not existing_dt:
        return True
    elif existing_dt and not candidate_dt:
        return False
    return _order_identity(candidate) > _order_identity(existing)


def _should_overlay_symbol_for_recent_fill(
    *,
    latest_order: TradeOrder | None,
    fill_order: TradeOrder,
    refreshed_dt: datetime,
) -> bool:
    latest_status = _normalize_order_status(getattr(latest_order, "status", None))
    if latest_status in _OVERLAY_ACTIVE_ORDER_STATUSES:
        return True
    return _order_is_recent(
        fill_order,
        reference_time=refreshed_dt,
        max_age_seconds=_OVERLAY_TERMINAL_FILL_GRACE_SECONDS,
    )


def _load_direct_order_baseline_qty(*, order_id: int, symbol: str) -> float | None:
    path = _resolve_bridge_root() / f"direct_{int(order_id)}" / "positions.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    items = payload.get("items") if isinstance(payload, dict) and isinstance(payload.get("items"), list) else []
    symbol_key = str(symbol or "").strip().upper()
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol") or "").strip().upper() != symbol_key:
            continue
        qty = _parse_position_quantity(item.get("quantity"))
        if qty is None:
            qty = _parse_position_quantity(item.get("position"))
        if qty is None:
            return None
        return float(qty)
    return 0.0


def _load_run_baseline_map(
    session,
    *,
    run_id: int,
    cache: dict[int, dict[str, float]],
) -> dict[str, float]:
    run_key = int(run_id)
    if run_key in cache:
        return cache[run_key]
    baseline_map: dict[str, float] = {}
    if session is None or not hasattr(session, "query"):
        cache[run_key] = baseline_map
        return baseline_map

    row = session.query(TradeRun).filter(TradeRun.id == run_key).first()
    params = row.params if row is not None and isinstance(row.params, dict) else {}
    baseline_payload = params.get("positions_baseline")
    items = baseline_payload.get("items") if isinstance(baseline_payload, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            qty = _parse_position_quantity(item.get("quantity"))
            if qty is None:
                qty = _parse_position_quantity(item.get("position"))
            if qty is None:
                continue
            baseline_map[symbol] = float(qty)
    cache[run_key] = baseline_map
    return baseline_map


def _load_order_baseline_qty(
    session,
    *,
    order: TradeOrder,
    run_baseline_cache: dict[int, dict[str, float]],
) -> float | None:
    symbol = str(order.symbol or "").strip().upper()
    if not symbol:
        return None
    if order.run_id is None:
        return _load_direct_order_baseline_qty(order_id=int(order.id), symbol=symbol)
    try:
        run_id = int(order.run_id)
    except (TypeError, ValueError):
        return None
    baseline_map = _load_run_baseline_map(session, run_id=run_id, cache=run_baseline_cache)
    return float(baseline_map.get(symbol, 0.0))


def _infer_positions_from_recent_direct_fills(
    session,
    *,
    mode: str,
    lookback_hours: int = 2,
    limit: int = 300,
    include_flattened: bool = False,
    max_fill_age_seconds: int = _INFER_RECENT_DIRECT_FILL_MAX_AGE_SECONDS,
) -> list[dict[str, object]]:
    if session is None or not hasattr(session, "query"):
        return []
    try:
        window_hours = max(1, int(lookback_hours))
    except (TypeError, ValueError):
        window_hours = 2
    window_start = (datetime.utcnow() - timedelta(hours=window_hours)).replace(tzinfo=None)

    rows = (
        session.query(TradeOrder)
        .filter(
            TradeOrder.status.in_(_DIRECT_FILL_STATUSES),
            TradeOrder.updated_at >= window_start,
        )
        .order_by(TradeOrder.updated_at.desc(), TradeOrder.id.desc())
        .limit(max(50, int(limit)))
        .all()
    )
    if not rows:
        return []

    mode_value = str(mode or "").strip().lower()
    reference_time = datetime.now(timezone.utc)
    latest_any_by_symbol: dict[str, TradeOrder] = {}
    all_rows = (
        session.query(TradeOrder)
        .filter(
            TradeOrder.updated_at >= window_start,
            TradeOrder.status.in_(_SYMBOL_LATEST_GUARD_STATUSES),
        )
        .order_by(TradeOrder.updated_at.desc(), TradeOrder.id.desc())
        .limit(max(200, int(limit) * 3))
        .all()
    )
    for order in all_rows:
        params = order.params if isinstance(order.params, dict) else {}
        order_mode = str(params.get("mode") or "").strip().lower()
        if order_mode and mode_value and order_mode != mode_value:
            continue
        symbol = str(order.symbol or "").strip().upper()
        if not symbol:
            continue
        existing = latest_any_by_symbol.get(symbol)
        if existing is None or _is_order_newer(order, existing):
            latest_any_by_symbol[symbol] = order

    run_baseline_cache: dict[int, dict[str, float]] = {}
    inferred_by_symbol: dict[str, dict[str, object]] = {}
    for order in rows:
        if _normalize_order_status(getattr(order, "status", None)) not in _DIRECT_FILL_STATUSES:
            continue
        if not _order_is_recent(
            order,
            reference_time=reference_time,
            max_age_seconds=max_fill_age_seconds,
        ):
            continue
        params = order.params if isinstance(order.params, dict) else {}
        order_mode = str(params.get("mode") or "").strip().lower()
        if mode_value and order_mode and order_mode != mode_value:
            continue
        symbol = str(order.symbol or "").strip().upper()
        if not symbol or symbol in inferred_by_symbol:
            continue
        latest_any = latest_any_by_symbol.get(symbol)
        if latest_any is not None and _order_identity(latest_any) != _order_identity(order):
            continue
        if not _should_overlay_symbol_for_recent_fill(
            latest_order=latest_any,
            fill_order=order,
            refreshed_dt=reference_time,
        ):
            continue
        baseline_qty = _load_order_baseline_qty(
            session,
            order=order,
            run_baseline_cache=run_baseline_cache,
        )
        if baseline_qty is None:
            continue

        try:
            quantity_target = abs(float(order.quantity or 0.0))
            filled_qty = abs(float(order.filled_quantity or 0.0))
        except (TypeError, ValueError):
            continue
        if filled_qty <= 0 and str(order.status or "").strip().upper() == "FILLED":
            filled_qty = quantity_target
        if quantity_target > 0:
            filled_qty = min(filled_qty, quantity_target) if filled_qty > 0 else filled_qty
        if filled_qty <= 0:
            continue

        side = str(order.side or "").strip().upper()
        if side == "BUY":
            expected_qty = baseline_qty + filled_qty
        elif side == "SELL":
            expected_qty = baseline_qty - filled_qty
        else:
            continue
        if abs(expected_qty) <= 1e-9 and not include_flattened:
            continue

        avg_cost = None
        try:
            avg_cost_value = float(order.avg_fill_price or order.limit_price or 0.0)
            if avg_cost_value > 0:
                avg_cost = avg_cost_value
        except (TypeError, ValueError):
            avg_cost = None

        inferred_by_symbol[symbol] = {
            "symbol": symbol,
            "position": float(expected_qty),
            "quantity": float(expected_qty),
            "avg_cost": avg_cost,
            "account": params.get("account"),
            "currency": params.get("currency"),
        }

    return [inferred_by_symbol[key] for key in sorted(inferred_by_symbol.keys())]


def _overlay_positions_with_recent_direct_fills(
    raw_items: list[dict[str, object]],
    inferred_items: list[dict[str, object]],
) -> tuple[list[dict[str, object]], bool]:
    inferred_by_symbol: dict[str, dict[str, object]] = {}
    for item in inferred_items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        inferred_by_symbol[symbol] = dict(item)
    if not inferred_by_symbol:
        return list(raw_items), False

    overlaid: list[dict[str, object]] = []
    touched_symbols: set[str] = set()
    changed = False

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        symbol = str(current.get("symbol") or "").strip().upper()
        if not symbol or symbol not in inferred_by_symbol:
            overlaid.append(current)
            continue

        touched_symbols.add(symbol)
        inferred = inferred_by_symbol[symbol]
        qty = _parse_position_quantity(inferred.get("position"))
        if qty is None:
            qty = _parse_position_quantity(inferred.get("quantity"))
        if qty is None:
            overlaid.append(current)
            continue

        current_qty = _parse_position_quantity(current.get("position"))
        if current_qty is None:
            current_qty = _parse_position_quantity(current.get("quantity"))

        if abs(qty) <= 1e-9:
            if current_qty is None or abs(current_qty) > 1e-9:
                changed = True
            continue

        merged = dict(current)
        merged.update(inferred)
        merged["symbol"] = symbol
        merged["position"] = float(qty)
        merged["quantity"] = float(qty)
        if current_qty is None or abs(current_qty - float(qty)) > 1e-9:
            changed = True
        overlaid.append(merged)

    for symbol in sorted(inferred_by_symbol.keys()):
        if symbol in touched_symbols:
            continue
        inferred = inferred_by_symbol[symbol]
        qty = _parse_position_quantity(inferred.get("position"))
        if qty is None:
            qty = _parse_position_quantity(inferred.get("quantity"))
        if qty is None or abs(qty) <= 1e-9:
            continue
        appended = dict(inferred)
        appended["symbol"] = symbol
        appended["position"] = float(qty)
        appended["quantity"] = float(qty)
        overlaid.append(appended)
        changed = True

    return overlaid, changed


def _is_positions_snapshot_inconsistent_with_recent_fills(
    session,
    *,
    mode: str,
    refreshed_at: object,
    items: list[dict[str, object]],
    max_fill_age_seconds: int = _OVERLAY_RECENT_DIRECT_FILL_MAX_AGE_SECONDS,
) -> bool:
    if session is None:
        return False

    refreshed_dt = _parse_timestamp(refreshed_at)
    if refreshed_dt is None:
        return False

    window_start = (refreshed_dt - timedelta(hours=2)).replace(tzinfo=None)
    orders = (
        session.query(TradeOrder)
        .filter(
            TradeOrder.status.in_(_DIRECT_FILL_STATUSES),
            TradeOrder.updated_at >= window_start,
        )
        .order_by(TradeOrder.updated_at.desc(), TradeOrder.id.desc())
        .limit(300)
        .all()
    )
    if not orders:
        return False

    mode_value = str(mode or "").strip().lower()
    latest_any_by_symbol: dict[str, TradeOrder] = {}
    all_rows = (
        session.query(TradeOrder)
        .filter(
            TradeOrder.updated_at >= window_start,
            TradeOrder.status.in_(_SYMBOL_LATEST_GUARD_STATUSES),
        )
        .order_by(TradeOrder.updated_at.desc(), TradeOrder.id.desc())
        .limit(1200)
        .all()
    )
    for order in all_rows:
        params = order.params if isinstance(order.params, dict) else {}
        order_mode = str(params.get("mode") or "").strip().lower()
        if order_mode and mode_value and order_mode != mode_value:
            continue
        symbol = str(order.symbol or "").strip().upper()
        if not symbol:
            continue
        existing = latest_any_by_symbol.get(symbol)
        if existing is None or _is_order_newer(order, existing):
            latest_any_by_symbol[symbol] = order

    positions_map: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        qty = _parse_position_quantity(item.get("position"))
        if qty is None:
            qty = _parse_position_quantity(item.get("quantity"))
        if qty is None:
            continue
        positions_map[symbol] = float(qty)

    latest_order_by_symbol: dict[str, TradeOrder] = {}
    for order in orders:
        params = order.params if isinstance(order.params, dict) else {}
        order_mode = str(params.get("mode") or "").strip().lower()
        if order_mode and mode_value and order_mode != mode_value:
            continue
        symbol = str(order.symbol or "").strip().upper()
        if not symbol:
            continue
        latest_any = latest_any_by_symbol.get(symbol)
        if latest_any is not None and _order_identity(latest_any) != _order_identity(order):
            continue
        updated_dt = _order_updated_at_utc(order)
        if updated_dt is None:
            continue
        existing = latest_order_by_symbol.get(symbol)
        if existing is None or _is_order_newer(order, existing):
            latest_order_by_symbol[symbol] = order

    run_baseline_cache: dict[int, dict[str, float]] = {}
    for symbol, order in latest_order_by_symbol.items():
        if _normalize_order_status(getattr(order, "status", None)) not in _DIRECT_FILL_STATUSES:
            continue
        if not _order_is_recent(
            order,
            reference_time=refreshed_dt,
            max_age_seconds=max_fill_age_seconds,
        ):
            continue
        latest_any = latest_any_by_symbol.get(symbol)
        if not _should_overlay_symbol_for_recent_fill(
            latest_order=latest_any,
            fill_order=order,
            refreshed_dt=refreshed_dt,
        ):
            continue
        baseline_qty = _load_order_baseline_qty(
            session,
            order=order,
            run_baseline_cache=run_baseline_cache,
        )
        if baseline_qty is None:
            continue
        try:
            filled_qty = abs(float(order.filled_quantity or 0.0))
            quantity_target = abs(float(order.quantity or 0.0))
        except (TypeError, ValueError):
            continue
        if quantity_target > 0:
            filled_qty = min(filled_qty, quantity_target)
        if filled_qty <= 0:
            continue
        side = str(order.side or "").strip().upper()
        expected = baseline_qty + filled_qty if side == "BUY" else baseline_qty - filled_qty
        current_qty = float(positions_map.get(symbol, 0.0))
        if abs(current_qty - expected) > 1e-6:
            return True
    return False


def _reconcile_non_stale_ib_holdings_with_recent_fills(
    session,
    *,
    mode: str,
    payload: dict[str, object],
) -> dict[str, object]:
    if session is None or not isinstance(payload, dict):
        return payload

    source_detail = payload.get("source_detail")
    stale = bool(payload.get("stale", True))
    if source_detail not in _VALID_HOLDINGS_SOURCE_DETAILS or stale:
        return payload

    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    inconsistent = _is_positions_snapshot_inconsistent_with_recent_fills(
        session,
        mode=mode,
        refreshed_at=refreshed_at,
        items=raw_items,
        max_fill_age_seconds=_OVERLAY_RECENT_DIRECT_FILL_MAX_AGE_SECONDS,
    )
    if not inconsistent:
        return payload

    ensure_lean_bridge_live(session, mode=mode, force=True)
    refreshed_payload = read_positions(_resolve_bridge_root())
    if isinstance(refreshed_payload, dict):
        refreshed_source_detail = refreshed_payload.get("source_detail")
        refreshed_stale = bool(refreshed_payload.get("stale", True))
        if refreshed_source_detail in _VALID_HOLDINGS_SOURCE_DETAILS and not refreshed_stale:
            payload = refreshed_payload
            refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
            raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
            inconsistent = _is_positions_snapshot_inconsistent_with_recent_fills(
                session,
                mode=mode,
                refreshed_at=refreshed_at,
                items=raw_items,
                max_fill_age_seconds=_OVERLAY_RECENT_DIRECT_FILL_MAX_AGE_SECONDS,
            )
            if not inconsistent:
                return payload

    inferred_items = _infer_positions_from_recent_direct_fills(
        session,
        mode=mode,
        include_flattened=True,
        max_fill_age_seconds=_OVERLAY_RECENT_DIRECT_FILL_MAX_AGE_SECONDS,
    )
    overlaid_items, changed = _overlay_positions_with_recent_direct_fills(raw_items, inferred_items)
    if not changed:
        return payload

    reconciled = dict(payload)
    reconciled["items"] = overlaid_items
    reconciled["stale"] = True
    reconciled["source_detail"] = "ib_holdings_overlay_recent_fills"
    return reconciled


def get_account_summary(
    session=None, *, mode: str, full: bool, force_refresh: bool = False
) -> dict[str, object]:
    cache_payload = _read_cached_summary()
    if cache_payload is None and CACHE_ROOT is not None:
        try:
            from app.services import lean_bridge as lean_bridge_service

            lean_bridge_service.refresh_bridge_cache()
        except Exception:
            pass
        cache_payload = _read_cached_summary()
    if cache_payload is not None:
        items = _normalize_items(cache_payload.get("items"))
        refreshed_at = cache_payload.get("refreshed_at")
        stale = bool(cache_payload.get("stale", False))
        source = cache_payload.get("source") or "cache"
        return {
            "items": items,
            "refreshed_at": refreshed_at,
            "source": source,
            "stale": stale,
            "full": full,
        }
    payload = read_account_summary(_resolve_bridge_root())
    items = _normalize_items(payload.get("items"))
    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
    stale = bool(payload.get("stale", True))
    source = payload.get("source") or "lean_bridge"
    return {
        "items": items,
        "refreshed_at": refreshed_at,
        "source": source,
        "stale": stale,
        "full": full,
    }


def get_account_positions(session, *, mode: str, force_refresh: bool = False) -> dict[str, object]:
    if force_refresh and session is not None:
        ensure_lean_bridge_live(session, mode=mode, force=True)

    payload = read_positions(_resolve_bridge_root())
    source_detail = payload.get("source_detail") if isinstance(payload, dict) else None
    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
    stale = bool(payload.get("stale", True))
    if source_detail not in _VALID_HOLDINGS_SOURCE_DETAILS or stale:
        if session is None:
            return {
                "items": [],
                "refreshed_at": refreshed_at,
                "stale": True,
                "source_detail": source_detail,
            }
        ensure_lean_bridge_live(session, mode=mode, force=True)
        payload = read_positions(_resolve_bridge_root())
        source_detail = payload.get("source_detail") if isinstance(payload, dict) else None
        refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
        stale = bool(payload.get("stale", True))
        if source_detail not in _VALID_HOLDINGS_SOURCE_DETAILS or stale:
            if source_detail in _VALID_HOLDINGS_SOURCE_DETAILS and stale:
                stale_items = payload.get("items") if isinstance(payload.get("items"), list) else []
                if stale_items:
                    payload = {
                        "items": stale_items,
                        "refreshed_at": refreshed_at,
                        "stale": True,
                        "source_detail": source_detail,
                    }
                    source_detail = payload["source_detail"]
                    stale = True
                else:
                    inferred_items = _infer_positions_from_recent_direct_fills(session, mode=mode)
                    if inferred_items:
                        payload = {
                            "items": inferred_items,
                            "refreshed_at": refreshed_at,
                            "stale": True,
                            "source_detail": "ib_holdings_inferred_recent_fills",
                        }
                        source_detail = payload["source_detail"]
                        stale = True
                    else:
                        return {
                            "items": [],
                            "refreshed_at": refreshed_at,
                            "stale": True,
                            "source_detail": source_detail,
                        }
            else:
                source_value = str(source_detail or "").strip().lower()
                if source_value not in {
                    "",
                    "ib_holdings",
                    "ib_holdings_empty",
                    "ib_holdings_error",
                    "brokerage_unavailable",
                }:
                    return {
                        "items": [],
                        "refreshed_at": refreshed_at,
                        "stale": True,
                        "source_detail": source_detail,
                    }
                inferred_items = _infer_positions_from_recent_direct_fills(session, mode=mode)
                if inferred_items:
                    payload = {
                        "items": inferred_items,
                        "refreshed_at": refreshed_at,
                        "stale": True,
                        "source_detail": "ib_holdings_inferred_recent_fills",
                    }
                    source_detail = payload["source_detail"]
                    stale = True
                else:
                    return {
                        "items": [],
                        "refreshed_at": refreshed_at,
                        "stale": True,
                        "source_detail": source_detail,
                    }
    payload = _reconcile_non_stale_ib_holdings_with_recent_fills(session, mode=mode, payload=payload)
    source_detail = payload.get("source_detail") if isinstance(payload, dict) else None
    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
    stale = bool(payload.get("stale", True))
    quotes_payload = read_quotes(_resolve_bridge_root())
    quote_items = quotes_payload.get("items") if isinstance(quotes_payload.get("items"), list) else []
    quote_prices: dict[str, float] = {}
    for item in quote_items:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not symbol:
            continue
        price = item.get("last")
        if price is None:
            bid = item.get("bid")
            ask = item.get("ask")
            if bid is not None and ask is not None:
                price = (float(bid) + float(ask)) / 2
            elif bid is not None:
                price = bid
            elif ask is not None:
                price = ask
        if price is None:
            continue
        try:
            quote_prices[str(symbol)] = float(price)
        except (TypeError, ValueError):
            continue
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    realized = None
    if session is not None:
        baseline = ensure_positions_baseline(_resolve_bridge_root(), payload)
        realized = compute_realized_pnl(session, baseline)
    items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if "position" not in normalized and "quantity" in normalized:
            normalized["position"] = normalized.get("quantity")
        symbol = normalized.get("symbol")
        position = normalized.get("position")
        avg_cost = normalized.get("avg_cost")
        market_price = normalized.get("market_price")
        quote_price = quote_prices.get(str(symbol)) if symbol is not None else None
        if (market_price is None or market_price == 0) and quote_price is not None:
            normalized["market_price"] = quote_price
            market_price = quote_price
        market_value = normalized.get("market_value")
        if (
            (market_value is None or market_value == 0)
            and market_price not in (None, 0, 0.0)
            and position not in (None, 0, 0.0)
        ):
            try:
                normalized["market_value"] = float(market_price) * float(position)
            except (TypeError, ValueError):
                pass
        unrealized = normalized.get("unrealized_pnl")
        if (
            (unrealized is None or unrealized == 0)
            and market_price not in (None, 0, 0.0)
            and avg_cost not in (None, 0, 0.0)
            and position not in (None, 0, 0.0)
        ):
            try:
                normalized["unrealized_pnl"] = (float(market_price) - float(avg_cost)) * float(position)
            except (TypeError, ValueError):
                pass
        if (
            normalized.get("market_price") is None
            and normalized.get("market_value") is not None
            and normalized.get("position") not in (None, 0, 0.0)
        ):
            try:
                normalized["market_price"] = float(normalized["market_value"]) / float(
                    normalized["position"]
                )
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if realized is not None:
            symbol_key = str(normalized.get("symbol") or "").strip().upper()
            if symbol_key:
                normalized["realized_pnl"] = realized.symbol_totals.get(symbol_key, 0.0)
        items.append(normalized)

    return {
        "items": items,
        "refreshed_at": refreshed_at,
        "stale": stale,
        "source_detail": source_detail,
    }


def get_account_positions_cached(
    session,
    *,
    mode: str,
    force_refresh: bool = False,
) -> dict[str, object]:
    cache_key = _account_positions_cache_key(mode=mode)
    cache_owner = False
    cache_event: Event | None = None

    if not force_refresh and _ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS > 0:
        cached = _get_account_positions_response_cache(cache_key)
        if cached is not None:
            return cached
        cache_owner, cache_event = _acquire_account_positions_response_inflight(cache_key)
        if not cache_owner:
            wait_timeout = max(
                0.05,
                min(
                    _ACCOUNT_POSITIONS_RESPONSE_INFLIGHT_WAIT_SECONDS,
                    max(_ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS * 2.0, 0.05),
                ),
            )
            cache_event.wait(timeout=wait_timeout)
            cached = _get_account_positions_response_cache(cache_key)
            if cached is not None:
                return cached
            cache_owner, cache_event = _acquire_account_positions_response_inflight(
                cache_key,
                allow_steal_stale=True,
            )
        if not cache_owner:
            # Avoid indefinite threadpool blocking when an inflight owner hangs.
            return _build_account_positions_fast_fallback(mode=mode)

    try:
        payload = get_account_positions(session, mode=mode, force_refresh=force_refresh)
        if _ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS > 0:
            _store_account_positions_response_cache(cache_key, payload)
        return payload
    finally:
        if cache_owner and cache_event is not None:
            _release_account_positions_response_inflight(cache_key, cache_event)


def fetch_account_summary(session) -> dict[str, float | str | None]:
    settings_row = get_or_create_ib_settings(session)
    mode = settings_row.mode or "paper"
    summary = get_account_summary(session, mode=mode, full=False, force_refresh=False)
    items = summary.get("items") if isinstance(summary.get("items"), dict) else {}
    cash_available = items.get("AvailableFunds") or items.get("CashBalance") or items.get("TotalCashValue")
    if isinstance(cash_available, str):
        try:
            cash_available = float(cash_available)
        except ValueError:
            pass
    output: dict[str, float | str | None] = dict(items)
    output["cash_available"] = cash_available
    return output
