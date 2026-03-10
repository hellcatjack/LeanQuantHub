from __future__ import annotations

import copy
from pathlib import Path
import json
import math
import socket
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

from app.core.config import settings
from app.models import TradeGuardState, TradeOrder, TradeRun
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.ib_settings import ensure_ib_client_id, get_or_create_ib_settings
from app.services.ib_read_session import (
    can_attempt_ib_transient_fallback,
    get_ib_read_session,
    record_ib_transient_fallback_result,
    resolve_ib_transient_client_id,
)
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
_VALID_HOLDINGS_SOURCE_DETAILS = {"ib_holdings", "ib_holdings_empty", "ib_holdings_ibapi_fallback"}
_DIRECT_FILL_STATUSES = ("FILLED", "PARTIAL")
_OVERLAY_RECENT_DIRECT_FILL_MAX_AGE_SECONDS = 7200
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
_IBAPI_VERIFY_TIMEOUT_SECONDS = max(
    float(getattr(settings, "ib_account_positions_ibapi_verify_timeout_seconds", 1.5) or 1.5),
    0.3,
)
_IBAPI_VERIFY_SOFT_TIMEOUT_SECONDS = max(
    float(getattr(settings, "ib_account_positions_ibapi_verify_soft_timeout_seconds", 0.35) or 0.35),
    0.3,
)
_IBAPI_VERIFY_MIN_INTERVAL_SECONDS = max(
    float(getattr(settings, "ib_account_positions_ibapi_verify_interval_seconds", 10.0) or 10.0),
    0.0,
)
_IBAPI_SUMMARY_VERIFY_TIMEOUT_SECONDS = max(
    float(getattr(settings, "ib_account_summary_ibapi_verify_timeout_seconds", 2.5) or 2.5),
    0.3,
)
_IBAPI_SUMMARY_VERIFY_MIN_INTERVAL_SECONDS = max(
    float(getattr(settings, "ib_account_summary_ibapi_verify_interval_seconds", 3.0) or 3.0),
    0.0,
)
_IBAPI_SUMMARY_VERIFY_FAILURE_INTERVAL_SECONDS = max(
    float(getattr(settings, "ib_account_summary_ibapi_verify_failure_interval_seconds", 20.0) or 20.0),
    0.0,
)
_IBAPI_PNL_VERIFY_TIMEOUT_SECONDS = max(
    float(getattr(settings, "ib_account_pnl_ibapi_verify_timeout_seconds", 2.5) or 2.5),
    0.3,
)
_IBAPI_PNL_VERIFY_MIN_INTERVAL_SECONDS = max(
    float(getattr(settings, "ib_account_pnl_ibapi_verify_interval_seconds", 3.0) or 3.0),
    0.0,
)
_IBAPI_SUMMARY_FALLBACK_TAGS = (
    "NetLiquidation",
    "NetLiquidationByCurrency",
    "UnrealizedPnL",
    "RealizedPnL",
    "TotalCashValue",
    "AvailableFunds",
    "CashBalance",
)
_SUMMARY_REQUIRED_PNL_TAGS = ("NetLiquidation", "UnrealizedPnL", "RealizedPnL")
_GUARD_EQUITY_MAX_AGE_SECONDS = max(
    int(getattr(settings, "ib_account_guard_equity_max_age_seconds", 86400) or 86400),
    60,
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
_ibapi_positions_verify_cache_lock = Lock()
_ibapi_positions_verify_cache: dict[str, tuple[float, str, dict[str, object] | None]] = {}
_ibapi_summary_verify_cache_lock = Lock()
_ibapi_summary_verify_cache: dict[str, tuple[float, str, dict[str, object] | None]] = {}
_ibapi_pnl_verify_cache_lock = Lock()
_ibapi_pnl_verify_cache: dict[str, tuple[float, str, dict[str, float] | None]] = {}
_ibapi_summary_account_cache_lock = Lock()
_ibapi_summary_account_cache: dict[str, str] = {}


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
    with _ibapi_positions_verify_cache_lock:
        _ibapi_positions_verify_cache.clear()
    with _ibapi_summary_verify_cache_lock:
        _ibapi_summary_verify_cache.clear()
    with _ibapi_pnl_verify_cache_lock:
        _ibapi_pnl_verify_cache.clear()
    with _ibapi_summary_account_cache_lock:
        _ibapi_summary_account_cache.clear()


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


def _ibapi_socket_reachable(*, host: str, port: int, timeout_seconds: float) -> bool:
    host_text = str(host or "").strip()
    try:
        port_value = int(port)
    except (TypeError, ValueError):
        return False
    if not host_text or port_value <= 0:
        return False
    try:
        timeout_value = float(timeout_seconds)
    except (TypeError, ValueError):
        timeout_value = 0.0
    probe_timeout = min(max(timeout_value, 0.2), 1.0)
    try:
        with socket.create_connection((host_text, port_value), timeout=probe_timeout):
            return True
    except Exception:
        return False


def _fetch_positions_via_ibapi(
    *,
    host: str,
    port: int,
    client_id: int,
    timeout_seconds: float = 6.0,
) -> list[dict[str, object]] | None:
    if not _ibapi_socket_reachable(host=host, port=port, timeout_seconds=timeout_seconds):
        return None
    # Lazy import so environments without ibapi can still import this module.
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    class _App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.ready = Event()
            self.done = Event()
            self.items: list[dict[str, object]] = []

        def nextValidId(self, _order_id: int):
            self.ready.set()

        def position(self, account, contract, pos, avgCost):
            symbol = str(getattr(contract, "symbol", "") or "").strip().upper()
            if not symbol:
                return
            try:
                qty = float(pos or 0.0)
            except (TypeError, ValueError):
                qty = 0.0
            try:
                avg_cost = float(avgCost or 0.0)
            except (TypeError, ValueError):
                avg_cost = 0.0
            self.items.append(
                {
                    "account": str(account or "").strip() or None,
                    "symbol": symbol,
                    "position": qty,
                    "quantity": qty,
                    "avg_cost": avg_cost if avg_cost > 0 else None,
                    "currency": str(getattr(contract, "currency", "") or "").strip() or None,
                }
            )

        def positionEnd(self):
            self.done.set()

    app = _App()
    thread: Thread | None = None
    try:
        app.connect(host, int(port), int(client_id))
        thread = Thread(target=app.run, daemon=True)
        thread.start()
        if not app.ready.wait(timeout_seconds):
            return None
        app.reqPositions()
        if not app.done.wait(timeout_seconds):
            return None
        return sorted(app.items, key=lambda x: str(x.get("symbol") or ""))
    except Exception:
        return None
    finally:
        try:
            app.disconnect()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=0.2)


def _load_positions_via_ibapi_fallback(
    session,
    *,
    mode: str,
    refreshed_at: object,
    timeout_seconds: float = 6.0,
) -> dict[str, object] | None:
    if session is None:
        return None
    try:
        settings_row = get_or_create_ib_settings(session)
    except Exception:
        return None
    host = str(getattr(settings_row, "host", "") or "").strip()
    try:
        port = int(getattr(settings_row, "port", 0) or 0)
    except (TypeError, ValueError):
        port = 0
    if not host or port <= 0:
        return None

    normalized_timeout = max(0.3, float(timeout_seconds))
    items = None
    shared_session = get_ib_read_session(
        mode=mode,
        host=host,
        port=port,
    )
    if shared_session is not None:
        shared_items = shared_session.fetch_positions(timeout_seconds=normalized_timeout)
        if isinstance(shared_items, list):
            items = [dict(item) for item in shared_items if isinstance(item, dict)]

    if items is None:
        purpose = "positions"
        if not can_attempt_ib_transient_fallback(
            mode=mode,
            host=host,
            port=port,
            purpose=purpose,
        ):
            return None
        client_id = resolve_ib_transient_client_id(mode=mode, purpose=purpose)
        items = _fetch_positions_via_ibapi(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=normalized_timeout,
        )
        record_ib_transient_fallback_result(
            mode=mode,
            host=host,
            port=port,
            purpose=purpose,
            success=items is not None,
        )
    if items is None:
        return None
    return {
        "items": items,
        "refreshed_at": refreshed_at or datetime.utcnow().isoformat() + "Z",
        "stale": False,
        "source_detail": "ib_holdings_ibapi_fallback",
    }


def probe_positions_via_ibapi(
    session,
    *,
    mode: str,
    timeout_seconds: float | None = None,
) -> dict[str, object]:
    started_at = monotonic()
    refreshed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    normalized_timeout = (
        _IBAPI_VERIFY_SOFT_TIMEOUT_SECONDS
        if timeout_seconds is None
        else max(0.3, float(timeout_seconds))
    )
    payload = _load_positions_via_ibapi_fallback(
        session,
        mode=mode,
        refreshed_at=refreshed_at,
        timeout_seconds=normalized_timeout,
    )
    latency_ms = max(0, int(round((monotonic() - started_at) * 1000.0)))
    if isinstance(payload, dict):
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "item_count": len(items),
            "refreshed_at": payload.get("refreshed_at") or refreshed_at,
            "source_detail": payload.get("source_detail"),
        }
    return {
        "ok": False,
        "latency_ms": latency_ms,
        "item_count": 0,
        "refreshed_at": refreshed_at,
        "error": "positions_probe_failed",
    }


def _positions_items_to_map(items: list[dict[str, object]]) -> dict[str, float]:
    positions: dict[str, float] = {}
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
        positions[symbol] = float(qty)
    return positions


def _positions_items_match(
    left_items: list[dict[str, object]],
    right_items: list[dict[str, object]],
    *,
    tolerance: float = 1e-6,
) -> bool:
    left_map = _positions_items_to_map(left_items)
    right_map = _positions_items_to_map(right_items)
    if left_map.keys() != right_map.keys():
        return False
    for symbol, left_qty in left_map.items():
        right_qty = float(right_map.get(symbol, 0.0))
        if abs(float(left_qty) - right_qty) > tolerance:
            return False
    return True


def _load_positions_via_ibapi_verified(
    session,
    *,
    mode: str,
    refreshed_at: object,
    force: bool = False,
) -> dict[str, object] | None:
    if session is None:
        return None
    mode_key = str(mode or "").strip().lower() or "paper"
    snapshot_token = str(refreshed_at or "").strip()
    now_mono = monotonic()
    if not force and _IBAPI_VERIFY_MIN_INTERVAL_SECONDS > 0:
        with _ibapi_positions_verify_cache_lock:
            cached_entry = _ibapi_positions_verify_cache.get(mode_key)
            if cached_entry is not None:
                cached_at, cached_token, cached_payload = cached_entry
                cache_age = now_mono - float(cached_at)
                # Reuse very recent probe result for this mode regardless of bridge snapshot token.
                # Bridge refreshed_at can tick every couple of seconds and would otherwise cause
                # unnecessary reconnect churn against Gateway/TWS.
                if cache_age < _IBAPI_VERIFY_MIN_INTERVAL_SECONDS:
                    return copy.deepcopy(cached_payload) if isinstance(cached_payload, dict) else None

    verify_timeout_seconds = _IBAPI_VERIFY_TIMEOUT_SECONDS
    if not force:
        # Keep default positions refresh responsive: this path is only a periodic consistency probe.
        verify_timeout_seconds = min(verify_timeout_seconds, _IBAPI_VERIFY_SOFT_TIMEOUT_SECONDS)

    payload = _load_positions_via_ibapi_fallback(
        session,
        mode=mode,
        refreshed_at=refreshed_at,
        timeout_seconds=verify_timeout_seconds,
    )
    with _ibapi_positions_verify_cache_lock:
        _ibapi_positions_verify_cache[mode_key] = (
            now_mono,
            snapshot_token,
            copy.deepcopy(payload) if isinstance(payload, dict) else None,
        )
    return payload


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
    by_currency: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            tag = str(name)
            value = item.get("value")
            items[tag] = value
            currency_text = str(item.get("currency") or "").strip().upper()
            if currency_text:
                by_currency.setdefault(tag, {})[currency_text] = value
            rows.append(
                {
                    "name": tag,
                    "value": value,
                    "currency": currency_text,
                    "account": str(item.get("account") or "").strip() or None,
                }
            )
    if by_currency:
        items["__by_currency__"] = by_currency
    if rows:
        items["__rows__"] = rows
    return items


def _has_summary_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _normalize_summary_currency_map(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, value in raw.items():
        currency = str(key or "").strip().upper()
        if not currency:
            continue
        if not _has_summary_value(value):
            continue
        normalized[currency] = value
    return normalized


def _collect_summary_by_currency(items: dict[str, object]) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    raw_by_currency = items.get("__by_currency__")
    if isinstance(raw_by_currency, dict):
        for tag, payload in raw_by_currency.items():
            tag_name = str(tag or "").strip()
            if not tag_name:
                continue
            normalized = _normalize_summary_currency_map(payload)
            if normalized:
                out[tag_name] = normalized
    for key, value in items.items():
        if not isinstance(key, str) or not key.endswith("ByCurrency"):
            continue
        tag_name = key[: -len("ByCurrency")]
        if not tag_name:
            continue
        normalized = _normalize_summary_currency_map(value)
        if not normalized:
            continue
        out.setdefault(tag_name, {}).update(normalized)
    return out


def _summary_needs_ibapi_enrichment(items: dict[str, object]) -> bool:
    by_currency = _collect_summary_by_currency(items)
    for tag in _SUMMARY_REQUIRED_PNL_TAGS:
        if _has_summary_value(items.get(tag)):
            continue
        if by_currency.get(tag):
            continue
        return True
    return False


def _summary_needs_core_enrichment(items: dict[str, object]) -> bool:
    by_currency = _collect_summary_by_currency(items)
    for tag in CORE_TAGS:
        if _has_summary_value(items.get(tag)):
            return False
        if by_currency.get(tag):
            return False
    return True


def _coerce_summary_numeric(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return float(parsed)


def _build_quote_price_map_for_summary(raw_items: list[dict[str, object]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        price = _coerce_summary_numeric(item.get("last"))
        if price in (None, 0.0):
            bid = _coerce_summary_numeric(item.get("bid"))
            ask = _coerce_summary_numeric(item.get("ask"))
            if bid is not None and ask is not None:
                price = (bid + ask) / 2.0
            elif bid is not None:
                price = bid
            elif ask is not None:
                price = ask
        if price is None or price == 0.0:
            continue
        prices[symbol] = float(price)
    return prices


def _build_account_summary_from_positions_snapshot(*, mode: str) -> dict[str, object] | None:
    root = _resolve_bridge_root()
    positions_payload = read_positions(root)
    source_detail = str(positions_payload.get("source_detail") or "").strip().lower()
    raw_positions = (
        positions_payload.get("items")
        if isinstance(positions_payload.get("items"), list)
        else []
    )
    if source_detail not in _VALID_HOLDINGS_SOURCE_DETAILS or not raw_positions:
        return None

    quotes_payload = read_quotes(root)
    quote_items = (
        quotes_payload.get("items")
        if isinstance(quotes_payload.get("items"), list)
        else []
    )
    quote_prices = _build_quote_price_map_for_summary(quote_items)

    net_position_value = 0.0
    gross_position_value = 0.0
    unrealized_total = 0.0
    unrealized_present = False

    for item in raw_positions:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        qty = _parse_position_quantity(item.get("position"))
        if qty is None:
            qty = _parse_position_quantity(item.get("quantity"))
        if qty is None:
            continue

        market_price = _coerce_summary_numeric(item.get("market_price"))
        if market_price in (None, 0.0) and symbol:
            market_price = quote_prices.get(symbol)
        market_value = _coerce_summary_numeric(item.get("market_value"))
        if market_value in (None, 0.0) and market_price is not None:
            market_value = float(market_price) * float(qty)
        if market_value is not None:
            net_position_value += float(market_value)
            gross_position_value += abs(float(market_value))

        unrealized = _coerce_summary_numeric(item.get("unrealized_pnl"))
        if unrealized in (None, 0.0) and market_price is not None:
            avg_cost = _coerce_summary_numeric(item.get("avg_cost"))
            if avg_cost is not None:
                unrealized = (float(market_price) - float(avg_cost)) * float(qty)
        if unrealized is not None:
            unrealized_total += float(unrealized)
            unrealized_present = True

    items: dict[str, object] = {}
    if abs(net_position_value) > 1e-9 or abs(gross_position_value) > 1e-9:
        net_liq = net_position_value if abs(net_position_value) > 1e-9 else gross_position_value
        items["NetLiquidation"] = net_liq
        items["EquityWithLoanValue"] = net_liq
        items["GrossPositionValue"] = (
            gross_position_value if abs(gross_position_value) > 1e-9 else abs(net_liq)
        )
    if unrealized_present:
        items["UnrealizedPnL"] = unrealized_total
    if not items:
        return None

    refreshed_at = (
        positions_payload.get("updated_at")
        or positions_payload.get("refreshed_at")
        or quotes_payload.get("updated_at")
        or quotes_payload.get("refreshed_at")
    )
    stale = bool(positions_payload.get("stale", True) or quotes_payload.get("stale", False))
    return {
        "items": items,
        "refreshed_at": refreshed_at,
        "stale": stale,
        "source": "derived_positions",
        "mode": mode,
    }


def _load_guard_equity_proxy(session, *, mode: str) -> float | None:
    if session is None or not hasattr(session, "query"):
        return None
    mode_key = str(mode or "").strip().lower()
    row = None
    try:
        query = session.query(TradeGuardState)
        if mode_key:
            row = (
                query.filter(TradeGuardState.mode == mode_key)
                .order_by(TradeGuardState.updated_at.desc(), TradeGuardState.id.desc())
                .first()
            )
        if row is None:
            row = query.order_by(TradeGuardState.updated_at.desc(), TradeGuardState.id.desc()).first()
    except Exception:
        return None
    if row is None:
        return None

    updated_at = getattr(row, "updated_at", None)
    if isinstance(updated_at, datetime):
        now_utc = datetime.now(timezone.utc)
        if updated_at.tzinfo is None:
            updated_utc = updated_at.replace(tzinfo=timezone.utc)
        else:
            updated_utc = updated_at.astimezone(timezone.utc)
        if (now_utc - updated_utc).total_seconds() > float(_GUARD_EQUITY_MAX_AGE_SECONDS):
            return None

    values: list[float] = []
    for raw in (
        getattr(row, "last_equity", None),
        getattr(row, "day_start_equity", None),
        getattr(row, "equity_peak", None),
    ):
        value = _coerce_summary_numeric(raw)
        if value is None or value <= 0:
            continue
        values.append(float(value))
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return float((ordered[middle - 1] + ordered[middle]) / 2.0)


def _should_apply_guard_equity(
    *,
    source: str,
    items: dict[str, object],
    guard_equity: float,
) -> bool:
    current_net_liq = _coerce_summary_numeric(items.get("NetLiquidation"))
    if current_net_liq is None:
        return True
    if "derived_positions" not in str(source or ""):
        return False
    gross_position_value = _coerce_summary_numeric(items.get("GrossPositionValue"))
    if gross_position_value is None:
        return False
    near_positions_only = abs(current_net_liq - gross_position_value) <= max(10.0, abs(gross_position_value) * 0.02)
    if not near_positions_only:
        return False
    return guard_equity > (gross_position_value * 1.02)


def _merge_summary_rows(
    base_rows: list[dict[str, object]],
    fallback_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for row in [*base_rows, *fallback_rows]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        currency = str(row.get("currency") or "").strip().upper()
        value = row.get("value")
        key = (name, currency)
        current = merged.get(key)
        if current is None:
            merged[key] = {"name": name, "value": value, "currency": currency}
            continue
        if not _has_summary_value(current.get("value")) and _has_summary_value(value):
            current["value"] = value
    return list(merged.values())


def _merge_account_summary_items(
    base_items: dict[str, object],
    fallback_items: dict[str, object],
) -> dict[str, object]:
    merged = dict(base_items)

    for key, value in fallback_items.items():
        if key in {"__by_currency__", "__rows__"}:
            continue
        if _has_summary_value(merged.get(key)):
            continue
        if _has_summary_value(value):
            merged[key] = value

    merged_by_currency = _collect_summary_by_currency(base_items)
    fallback_by_currency = _collect_summary_by_currency(fallback_items)
    for tag, currency_map in fallback_by_currency.items():
        merged_by_currency.setdefault(tag, {}).update(currency_map)
    if merged_by_currency:
        merged["__by_currency__"] = merged_by_currency
        for tag, currency_map in merged_by_currency.items():
            merged[f"{tag}ByCurrency"] = dict(currency_map)

    base_rows = base_items.get("__rows__") if isinstance(base_items.get("__rows__"), list) else []
    fallback_rows = fallback_items.get("__rows__") if isinstance(fallback_items.get("__rows__"), list) else []
    rows = _merge_summary_rows(base_rows, fallback_rows)
    if rows:
        merged["__rows__"] = rows

    return merged


def _fetch_account_summary_via_ibapi(
    *,
    host: str,
    port: int,
    client_id: int,
    timeout_seconds: float = 6.0,
    account_id: str | None = None,
) -> list[dict[str, object]] | None:
    if not _ibapi_socket_reachable(host=host, port=port, timeout_seconds=timeout_seconds):
        return None
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    class _App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.ready = Event()
            self.done = Event()
            self.req_id = 900_000 + int(monotonic() * 1000) % 100_000
            self.items: list[dict[str, object]] = []

        def nextValidId(self, _order_id: int):
            self.ready.set()

        def accountSummary(self, reqId, account, tag, value, currency):
            if reqId != self.req_id:
                return
            account_text = str(account or "").strip()
            if normalized_account and account_text and account_text.upper() != normalized_account:
                return
            self.items.append(
                {
                    "name": str(tag or "").strip(),
                    "value": value,
                    "currency": str(currency or "").strip().upper(),
                    "account": account_text or None,
                }
            )

        def accountSummaryEnd(self, reqId):
            if reqId == self.req_id:
                self.done.set()

    normalized_account = str(account_id or "").strip().upper() or None
    app = _App()
    thread: Thread | None = None
    tags = ",".join(_IBAPI_SUMMARY_FALLBACK_TAGS)
    try:
        app.connect(host, int(port), int(client_id))
        thread = Thread(target=app.run, daemon=True)
        thread.start()
        if not app.ready.wait(timeout_seconds):
            return None
        app.reqAccountSummary(app.req_id, "All", tags)
        if not app.done.wait(timeout_seconds):
            return None
        return [item for item in app.items if str(item.get("name") or "").strip()]
    except Exception:
        return None
    finally:
        try:
            app.cancelAccountSummary(getattr(app, "req_id", 0))
        except Exception:
            pass
        try:
            app.disconnect()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=0.2)


def _load_account_summary_via_ibapi_fallback(
    session,
    *,
    mode: str,
    refreshed_at: object,
    timeout_seconds: float = 6.0,
) -> dict[str, object] | None:
    if session is None:
        return None
    mode_key = str(mode or "").strip().lower() or "paper"
    try:
        settings_row = get_or_create_ib_settings(session)
    except Exception:
        return None
    host = str(getattr(settings_row, "host", "") or "").strip()
    try:
        port = int(getattr(settings_row, "port", 0) or 0)
    except (TypeError, ValueError):
        port = 0
    if not host or port <= 0:
        return None

    account_id = str(getattr(settings_row, "account_id", "") or "").strip() or None
    normalized_timeout = max(0.3, float(timeout_seconds))
    rows = None
    shared_session = get_ib_read_session(
        mode=mode,
        host=host,
        port=port,
    )
    if shared_session is not None:
        shared_rows = shared_session.fetch_account_summary(
            tags=_IBAPI_SUMMARY_FALLBACK_TAGS,
            account_id=account_id,
            timeout_seconds=normalized_timeout,
        )
        if isinstance(shared_rows, list):
            rows = [dict(item) for item in shared_rows if isinstance(item, dict)]

    if rows is None:
        purpose = "summary"
        if not can_attempt_ib_transient_fallback(
            mode=mode,
            host=host,
            port=port,
            purpose=purpose,
        ):
            return None
        client_id = resolve_ib_transient_client_id(mode=mode, purpose=purpose)
        rows = _fetch_account_summary_via_ibapi(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=normalized_timeout,
            account_id=account_id,
        )
        record_ib_transient_fallback_result(
            mode=mode,
            host=host,
            port=port,
            purpose=purpose,
            success=bool(rows),
        )
    if not rows:
        return None
    resolved_account = account_id
    if not resolved_account:
        for row in rows:
            if not isinstance(row, dict):
                continue
            account_text = str(row.get("account") or "").strip()
            if account_text:
                resolved_account = account_text
                break
    if resolved_account:
        with _ibapi_summary_account_cache_lock:
            _ibapi_summary_account_cache[mode_key] = resolved_account
    return {
        "items": _normalize_items(rows),
        "account_id": resolved_account,
        "refreshed_at": refreshed_at or datetime.utcnow().isoformat() + "Z",
        "stale": False,
        "source": "ibapi",
        "mode": mode,
    }


def _load_account_summary_via_ibapi_verified(
    session,
    *,
    mode: str,
    refreshed_at: object,
    force: bool = False,
    timeout_seconds: float | None = None,
) -> dict[str, object] | None:
    mode_key = str(mode or "").strip().lower() or "paper"
    now_mono = monotonic()
    snapshot_token = str(refreshed_at or "")
    if not force and _IBAPI_SUMMARY_VERIFY_MIN_INTERVAL_SECONDS > 0:
        with _ibapi_summary_verify_cache_lock:
            cached_entry = _ibapi_summary_verify_cache.get(mode_key)
            if cached_entry is not None:
                cached_at, cached_token, cached_payload = cached_entry
                cache_age = now_mono - float(cached_at)
                # Keep a short mode-level cooldown for successful/failed probes to prevent
                # bursty reconnect loops when bridge snapshot token changes quickly.
                if isinstance(cached_payload, dict):
                    if cache_age < _IBAPI_SUMMARY_VERIFY_MIN_INTERVAL_SECONDS:
                        return copy.deepcopy(cached_payload)
                else:
                    failure_interval = max(
                        _IBAPI_SUMMARY_VERIFY_MIN_INTERVAL_SECONDS,
                        _IBAPI_SUMMARY_VERIFY_FAILURE_INTERVAL_SECONDS,
                    )
                    if cache_age < failure_interval:
                        return None

    verify_timeout_seconds = (
        _IBAPI_SUMMARY_VERIFY_TIMEOUT_SECONDS
        if timeout_seconds is None
        else max(0.3, float(timeout_seconds))
    )
    payload = _load_account_summary_via_ibapi_fallback(
        session,
        mode=mode,
        refreshed_at=refreshed_at,
        timeout_seconds=verify_timeout_seconds,
    )
    with _ibapi_summary_verify_cache_lock:
        _ibapi_summary_verify_cache[mode_key] = (
            now_mono,
            snapshot_token,
            copy.deepcopy(payload) if isinstance(payload, dict) else None,
        )
    return payload


def _coerce_ibapi_pnl_value(raw: object) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    # IB uses very large sentinel values for "unset".
    if abs(value) >= 1e100:
        return None
    return value


def _fetch_account_pnl_via_ibapi(
    *,
    host: str,
    port: int,
    client_id: int,
    account_id: str,
    timeout_seconds: float = 6.0,
) -> dict[str, float] | None:
    if not _ibapi_socket_reachable(host=host, port=port, timeout_seconds=timeout_seconds):
        return None
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    class _App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.ready = Event()
            self.done = Event()
            self.req_id = 950_000 + int(monotonic() * 1000) % 100_000
            self.payload: dict[str, float] = {}

        def nextValidId(self, _order_id: int):
            self.ready.set()

        def pnl(self, reqId, dailyPnL, unrealizedPnL, realizedPnL):
            if reqId != self.req_id:
                return
            unrealized = _coerce_ibapi_pnl_value(unrealizedPnL)
            realized = _coerce_ibapi_pnl_value(realizedPnL)
            daily = _coerce_ibapi_pnl_value(dailyPnL)
            if unrealized is not None:
                self.payload["UnrealizedPnL"] = unrealized
            if realized is not None:
                self.payload["RealizedPnL"] = realized
            if daily is not None:
                self.payload["DailyPnL"] = daily
            if self.payload:
                self.done.set()

    app = _App()
    thread: Thread | None = None
    try:
        app.connect(host, int(port), int(client_id))
        thread = Thread(target=app.run, daemon=True)
        thread.start()
        if not app.ready.wait(timeout_seconds):
            return None
        app.reqPnL(app.req_id, str(account_id), "")
        if not app.done.wait(timeout_seconds):
            return None
        return dict(app.payload) if app.payload else None
    except Exception:
        return None
    finally:
        try:
            app.cancelPnL(getattr(app, "req_id", 0))
        except Exception:
            pass
        try:
            app.disconnect()
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout=0.2)


def _load_account_pnl_via_ibapi_fallback(
    session,
    *,
    mode: str,
    refreshed_at: object,
    timeout_seconds: float = 6.0,
) -> dict[str, float] | None:
    if session is None:
        return None
    mode_key = str(mode or "").strip().lower() or "paper"
    try:
        settings_row = get_or_create_ib_settings(session)
    except Exception:
        return None
    host = str(getattr(settings_row, "host", "") or "").strip()
    try:
        port = int(getattr(settings_row, "port", 0) or 0)
    except (TypeError, ValueError):
        port = 0
    account_id = str(getattr(settings_row, "account_id", "") or "").strip()
    if not account_id:
        with _ibapi_summary_account_cache_lock:
            account_id = str(_ibapi_summary_account_cache.get(mode_key) or "").strip()
    if not host or port <= 0 or not account_id:
        return None

    normalized_timeout = max(0.3, float(timeout_seconds))
    pnl = None
    shared_session = get_ib_read_session(
        mode=mode,
        host=host,
        port=port,
    )
    if shared_session is not None:
        shared_pnl = shared_session.fetch_account_pnl(
            account_id=account_id,
            timeout_seconds=normalized_timeout,
        )
        if isinstance(shared_pnl, dict):
            pnl = dict(shared_pnl)

    if pnl is None:
        purpose = "pnl"
        if not can_attempt_ib_transient_fallback(
            mode=mode,
            host=host,
            port=port,
            purpose=purpose,
        ):
            return None
        client_id = resolve_ib_transient_client_id(mode=mode, purpose=purpose)
        pnl = _fetch_account_pnl_via_ibapi(
            host=host,
            port=port,
            client_id=client_id,
            timeout_seconds=normalized_timeout,
            account_id=account_id,
        )
        record_ib_transient_fallback_result(
            mode=mode,
            host=host,
            port=port,
            purpose=purpose,
            success=bool(pnl),
        )
    if not pnl:
        return None
    return pnl


def _load_account_pnl_via_ibapi_verified(
    session,
    *,
    mode: str,
    refreshed_at: object,
    force: bool = False,
) -> dict[str, float] | None:
    mode_key = str(mode or "").strip().lower() or "paper"
    now_mono = monotonic()
    snapshot_token = str(refreshed_at or "")
    if not force and _IBAPI_PNL_VERIFY_MIN_INTERVAL_SECONDS > 0:
        with _ibapi_pnl_verify_cache_lock:
            cached_entry = _ibapi_pnl_verify_cache.get(mode_key)
            if cached_entry is not None:
                cached_at, cached_token, cached_payload = cached_entry
                cache_age = now_mono - float(cached_at)
                if cache_age < _IBAPI_PNL_VERIFY_MIN_INTERVAL_SECONDS:
                    return copy.deepcopy(cached_payload) if isinstance(cached_payload, dict) else None

    payload = _load_account_pnl_via_ibapi_fallback(
        session,
        mode=mode,
        refreshed_at=refreshed_at,
        timeout_seconds=_IBAPI_PNL_VERIFY_TIMEOUT_SECONDS,
    )
    with _ibapi_pnl_verify_cache_lock:
        _ibapi_pnl_verify_cache[mode_key] = (
            now_mono,
            snapshot_token,
            copy.deepcopy(payload) if isinstance(payload, dict) else None,
        )
    return payload


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

    ibapi_payload = _load_positions_via_ibapi_fallback(
        session,
        mode=mode,
        refreshed_at=refreshed_at,
    )
    if isinstance(ibapi_payload, dict):
        ibapi_items = ibapi_payload.get("items") if isinstance(ibapi_payload.get("items"), list) else []
        # Prefer IB API fallback when we can retrieve non-empty holdings, or when bridge
        # snapshot is empty but we explicitly confirmed live reachability.
        if ibapi_items or not raw_items:
            return ibapi_payload

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
    source = "lean_bridge"
    source_detail = None
    stale = True
    refreshed_at = None
    items: dict[str, object] = {}

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
        source_detail = cache_payload.get("source_detail")
    else:
        payload = read_account_summary(_resolve_bridge_root())
        items = _normalize_items(payload.get("items"))
        refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
        stale = bool(payload.get("stale", True))
        source = payload.get("source") or "lean_bridge"
        source_detail = payload.get("source_detail")

    guard_equity = _load_guard_equity_proxy(session, mode=mode)
    needs_enrichment = _summary_needs_ibapi_enrichment(items) if full else _summary_needs_core_enrichment(items)
    source_detail_text = str(source_detail or "").strip().lower()
    if (
        session is not None
        and hasattr(session, "query")
        and not full
        and not force_refresh
        and needs_enrichment
        and source_detail_text == "ib_account_empty"
    ):
        # Keep the lightweight overview responsive when bridge account summary is empty.
        quick_derived = _build_account_summary_from_positions_snapshot(mode=mode)
        if isinstance(quick_derived, dict):
            quick_items = _normalize_items(quick_derived.get("items"))
            if quick_items:
                items = _merge_account_summary_items(items, quick_items)
                source = f"{source}+derived_positions"
                stale = bool(stale or bool(quick_derived.get("stale", True)))
                if not refreshed_at:
                    refreshed_at = quick_derived.get("refreshed_at")
                needs_enrichment = _summary_needs_core_enrichment(items)

    if (
        session is not None
        and hasattr(session, "query")
        and needs_enrichment
    ):
        summary_probe_timeout = _IBAPI_SUMMARY_VERIFY_TIMEOUT_SECONDS
        if not full and not force_refresh:
            if source_detail_text == "ib_account_empty":
                summary_probe_timeout = min(summary_probe_timeout, 0.35)
        ibapi_payload = _load_account_summary_via_ibapi_verified(
            session,
            mode=mode,
            refreshed_at=refreshed_at,
            force=force_refresh,
            timeout_seconds=summary_probe_timeout,
        )
        if isinstance(ibapi_payload, dict):
            ibapi_items = _normalize_items(ibapi_payload.get("items"))
            if ibapi_items:
                items = _merge_account_summary_items(items, ibapi_items)
                ibapi_source = str(ibapi_payload.get("source") or "ibapi").strip() or "ibapi"
                source = f"{source}+{ibapi_source}"
                stale = bool(stale and bool(ibapi_payload.get("stale", False)))
                if not refreshed_at:
                    refreshed_at = ibapi_payload.get("refreshed_at")
                needs_enrichment = (
                    _summary_needs_ibapi_enrichment(items)
                    if full
                    else _summary_needs_core_enrichment(items)
                )

    if (
        full
        and session is not None
        and hasattr(session, "query")
        and (
            not _has_summary_value(items.get("RealizedPnL"))
            or not _has_summary_value(items.get("UnrealizedPnL"))
        )
    ):
        pnl_payload = _load_account_pnl_via_ibapi_verified(
            session,
            mode=mode,
            refreshed_at=refreshed_at,
            force=force_refresh,
        )
        pnl_applied = False
        if isinstance(pnl_payload, dict):
            if not _has_summary_value(items.get("RealizedPnL")) and _has_summary_value(pnl_payload.get("RealizedPnL")):
                items["RealizedPnL"] = pnl_payload.get("RealizedPnL")
                pnl_applied = True
            if not _has_summary_value(items.get("UnrealizedPnL")) and _has_summary_value(
                pnl_payload.get("UnrealizedPnL")
            ):
                items["UnrealizedPnL"] = pnl_payload.get("UnrealizedPnL")
                pnl_applied = True
        if pnl_applied:
            source = f"{source}+ibapi_pnl"

    needs_enrichment = _summary_needs_ibapi_enrichment(items) if full else _summary_needs_core_enrichment(items)
    if (
        session is not None
        and hasattr(session, "query")
        and needs_enrichment
    ):
        derived_payload = _build_account_summary_from_positions_snapshot(mode=mode)
        if isinstance(derived_payload, dict):
            derived_items = _normalize_items(derived_payload.get("items"))
            if derived_items:
                items = _merge_account_summary_items(items, derived_items)
                source = f"{source}+derived_positions"
                stale = bool(stale or bool(derived_payload.get("stale", True)))
                if not refreshed_at:
                    refreshed_at = derived_payload.get("refreshed_at")

    if guard_equity is not None and _should_apply_guard_equity(source=source, items=items, guard_equity=guard_equity):
        items["NetLiquidation"] = guard_equity
        items["EquityWithLoanValue"] = guard_equity
        if "guard_equity" not in str(source or ""):
            source = f"{source}+guard_equity"
        stale = True

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
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    can_use_stale_bridge_snapshot = bool(
        not force_refresh
        and stale
        and source_detail in _VALID_HOLDINGS_SOURCE_DETAILS
        and len(raw_items) > 0
    )

    # Guardrail: bridge positions snapshots can look fresh while drifting from TWS.
    # Periodically verify against a direct reqPositions snapshot and prefer TWS when mismatched.
    if (
        session is not None
        and hasattr(session, "query")
        and source_detail in _VALID_HOLDINGS_SOURCE_DETAILS
        and not stale
        and (force_refresh or source_detail != "ib_holdings_ibapi_fallback")
    ):
        ibapi_verified = _load_positions_via_ibapi_verified(
            session,
            mode=mode,
            refreshed_at=refreshed_at,
            force=force_refresh,
        )
        if isinstance(ibapi_verified, dict):
            bridge_items = payload.get("items") if isinstance(payload.get("items"), list) else []
            ibapi_items = (
                ibapi_verified.get("items")
                if isinstance(ibapi_verified.get("items"), list)
                else []
            )
            if force_refresh or not _positions_items_match(bridge_items, ibapi_items):
                payload = ibapi_verified
                source_detail = payload.get("source_detail")
                refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
                stale = bool(payload.get("stale", True))

    if source_detail not in _VALID_HOLDINGS_SOURCE_DETAILS or stale:
        if session is None and not can_use_stale_bridge_snapshot:
            return {
                "items": [],
                "refreshed_at": refreshed_at,
                "stale": True,
                "source_detail": source_detail,
            }
        if not can_use_stale_bridge_snapshot:
            ensure_force_refresh = bool(force_refresh or source_detail not in _VALID_HOLDINGS_SOURCE_DETAILS)
            ensure_lean_bridge_live(session, mode=mode, force=ensure_force_refresh)
            payload = read_positions(_resolve_bridge_root())
            source_detail = payload.get("source_detail") if isinstance(payload, dict) else None
            refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
            stale = bool(payload.get("stale", True))
            if source_detail not in _VALID_HOLDINGS_SOURCE_DETAILS or stale:
                # Position list must stay aligned with TWS only:
                # prefer direct IB API holdings and avoid any local inferred overlay.
                ibapi_timeout_seconds = (
                    _IBAPI_VERIFY_TIMEOUT_SECONDS
                    if not force_refresh
                    else max(0.3, _IBAPI_VERIFY_TIMEOUT_SECONDS * 2.0)
                )
                ibapi_payload = _load_positions_via_ibapi_fallback(
                    session,
                    mode=mode,
                    refreshed_at=refreshed_at,
                    timeout_seconds=ibapi_timeout_seconds,
                )
                if isinstance(ibapi_payload, dict):
                    payload = ibapi_payload
                    source_detail = payload.get("source_detail") if isinstance(payload, dict) else None
                    refreshed_at = payload.get("updated_at") or payload.get("refreshed_at")
                    stale = bool(payload.get("stale", True))
                elif source_detail in _VALID_HOLDINGS_SOURCE_DETAILS:
                    stale_items = payload.get("items") if isinstance(payload.get("items"), list) else []
                    payload = {
                        "items": stale_items,
                        "refreshed_at": refreshed_at,
                        "stale": True,
                        "source_detail": source_detail,
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
            # Avoid returning a divergent fallback payload under contention.
            payload = get_account_positions(session, mode=mode, force_refresh=False)
            if _ACCOUNT_POSITIONS_RESPONSE_CACHE_TTL_SECONDS > 0:
                _store_account_positions_response_cache(cache_key, payload)
            return payload

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
