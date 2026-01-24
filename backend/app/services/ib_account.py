from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import threading
from typing import Any

try:
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.wrapper import EWrapper
    _IBAPI_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    EClient = object  # type: ignore[assignment]
    Contract = object  # type: ignore[assignment]
    EWrapper = object  # type: ignore[assignment]
    _IBAPI_AVAILABLE = False

from app.services.ib_market import _ib_data_root, fetch_market_snapshots, ib_request_lock
from app.services.ib_settings import ensure_ib_client_id, get_or_create_ib_settings, resolve_ib_api_mode

CORE_TAGS = {
    "NetLiquidation",
    "TotalCashValue",
    "AvailableFunds",
    "BuyingPower",
    "GrossPositionValue",
    "EquityWithLoanValue",
    "UnrealizedPnL",
    "RealizedPnL",
    "InitMarginReq",
    "MaintMarginReq",
    "AccruedCash",
    "CashBalance",
}

SUMMARY_TTL_SECONDS = 60

_FATAL_ERROR_CODES = {502, 503, 504, 1100, 1101, 1102}


class IBAccountSession(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, timeout: float = 5.0) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._summary_event = threading.Event()
        self._positions_event = threading.Event()
        self._summary: dict[str, str] = {}
        self._positions: list[dict[str, object]] = []
        self._error: str | None = None

    def __enter__(self) -> "IBAccountSession":
        if not _IBAPI_AVAILABLE:
            raise RuntimeError("ibapi_not_available")
        self.connect(self._host, self._port, self._client_id)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        if not self._ready.wait(self._timeout):
            self.disconnect()
            raise RuntimeError("ib_account_timeout")
        if self._error:
            self.disconnect()
            raise RuntimeError(self._error)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.isConnected():
            self.disconnect()
        if self._thread:
            self._thread.join(timeout=1.0)

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self._ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # type: ignore[override]  # noqa: N802
        if errorCode in _FATAL_ERROR_CODES:
            self._error = f"{errorCode}:{errorString}"
            self._ready.set()
            self._summary_event.set()
            self._positions_event.set()

    def accountSummary(self, reqId, account, tag, value, currency):  # noqa: N802
        if tag:
            self._summary[str(tag)] = str(value)

    def accountSummaryEnd(self, reqId):  # noqa: N802
        self._summary_event.set()

    def position(self, account, contract, position, avgCost):  # noqa: N802
        symbol = getattr(contract, "symbol", None)
        if not symbol:
            return
        payload = {
            "symbol": str(symbol).strip().upper(),
            "position": float(position),
            "avg_cost": float(avgCost) if avgCost is not None else None,
            "account": str(account) if account is not None else None,
            "currency": getattr(contract, "currency", None),
        }
        self._positions.append(payload)

    def positionEnd(self):  # noqa: N802
        self._positions_event.set()

    def request_account_summary(self, account_id: str | None, timeout: float | None = None) -> dict[str, str]:
        req_id = 9001
        group = account_id or "All"
        self.reqAccountSummary(req_id, group, "All")
        self._summary_event.wait(timeout or self._timeout)
        self.cancelAccountSummary(req_id)
        return dict(self._summary)

    def request_positions(self, timeout: float | None = None) -> list[dict[str, object]]:
        self.reqPositions()
        self._positions_event.wait(timeout or self._timeout)
        self.cancelPositions()
        return list(self._positions)


def _parse_value(value: str) -> float | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return text


def _filter_summary(raw: dict[str, str], full: bool) -> dict[str, object]:
    items: dict[str, object] = {}
    for key, value in raw.items():
        if full or key in CORE_TAGS:
            items[key] = _parse_value(value)
    return items


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _is_stale(refreshed_at: str | None) -> bool:
    ts = _parse_timestamp(refreshed_at)
    if ts is None:
        return True
    age = (datetime.utcnow() - ts).total_seconds()
    return age >= SUMMARY_TTL_SECONDS


def _summary_cache_path(mode: str) -> Path:
    root = _ib_data_root() / "account"
    root.mkdir(parents=True, exist_ok=True)
    safe_mode = mode or "paper"
    return root / f"summary_{safe_mode}.json"


def _positions_cache_path(mode: str) -> Path:
    root = _ib_data_root() / "account"
    root.mkdir(parents=True, exist_ok=True)
    safe_mode = mode or "paper"
    return root / f"positions_{safe_mode}.json"


def read_cached_summary(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def read_cached_positions(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_cached_summary(cache_path: Path, raw: dict[str, str], refreshed_at: datetime | None) -> None:
    payload = {
        "raw": raw,
        "refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_cached_positions(cache_path: Path, raw: list[dict[str, object]], refreshed_at: datetime | None) -> None:
    payload = {
        "items": raw,
        "refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_summary_payload(raw: dict[str, str], refreshed_at: str | None, source: str, stale: bool, full: bool) -> dict[str, object]:
    return {
        "items": _filter_summary(raw, full=full),
        "refreshed_at": refreshed_at,
        "source": source,
        "stale": stale,
        "full": full,
    }


def _pick_snapshot_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    if "price" in snapshot and snapshot.get("price") is not None:
        try:
            return float(snapshot.get("price"))
        except (TypeError, ValueError):
            return None
    payload = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else snapshot
    if not isinstance(payload, dict):
        return None
    for key in ("last", "close", "bid", "ask"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _merge_position_prices(
    positions: list[dict[str, object]],
    snapshots: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    for position in positions:
        symbol = str(position.get("symbol") or "").strip().upper()
        snapshot = snapshots.get(symbol) or {}
        price = _pick_snapshot_price(snapshot)
        qty = position.get("position")
        avg_cost = position.get("avg_cost")
        market_value = None
        unrealized_pnl = None
        if price is not None and isinstance(qty, (int, float)):
            market_value = float(price) * float(qty)
        if price is not None and isinstance(qty, (int, float)) and isinstance(avg_cost, (int, float)):
            unrealized_pnl = (float(price) - float(avg_cost)) * float(qty)
        payload = dict(position)
        if price is not None:
            payload["market_price"] = price
        if market_value is not None:
            payload["market_value"] = market_value
        if unrealized_pnl is not None:
            payload["unrealized_pnl"] = unrealized_pnl
        merged.append(payload)
    return merged


def _fetch_account_summary(session, mode: str) -> dict[str, str]:
    settings_row = ensure_ib_client_id(session)
    if resolve_ib_api_mode(settings_row) == "mock":
        return {}
    try:
        with ib_request_lock():
            with IBAccountSession(
                settings_row.host,
                settings_row.port,
                settings_row.client_id,
                timeout=5.0,
            ) as api:
                return api.request_account_summary(settings_row.account_id)
    except Exception:
        return {}


def _fetch_account_positions(session, mode: str) -> list[dict[str, object]]:
    settings_row = ensure_ib_client_id(session)
    if resolve_ib_api_mode(settings_row) == "mock":
        return []
    try:
        with ib_request_lock():
            with IBAccountSession(
                settings_row.host,
                settings_row.port,
                settings_row.client_id,
                timeout=5.0,
            ) as api:
                return api.request_positions()
    except Exception:
        return []


def get_account_summary(session, *, mode: str, full: bool, force_refresh: bool = False) -> dict[str, object]:
    cache_path = _summary_cache_path(mode)
    cached = read_cached_summary(cache_path)
    if cached and not force_refresh:
        raw = cached.get("raw") if isinstance(cached.get("raw"), dict) else {}
        refreshed_at = cached.get("refreshed_at")
        stale = _is_stale(refreshed_at)
        return _build_summary_payload(raw, refreshed_at, "cache", stale, full)
    raw = _fetch_account_summary(session, mode)
    if raw:
        refreshed_at = datetime.utcnow()
        write_cached_summary(cache_path, raw, refreshed_at)
        return _build_summary_payload(raw, refreshed_at.isoformat(), "refresh", False, full)
    if cached:
        raw = cached.get("raw") if isinstance(cached.get("raw"), dict) else {}
        refreshed_at = cached.get("refreshed_at")
        return _build_summary_payload(raw, refreshed_at, "cache", True, full)
    return {
        "items": {},
        "refreshed_at": None,
        "source": "cache",
        "stale": True,
        "full": full,
    }


def get_account_positions(session, *, mode: str, force_refresh: bool = False) -> dict[str, object]:
    cache_path = _positions_cache_path(mode)
    cached = read_cached_positions(cache_path)
    if cached and not force_refresh:
        refreshed_at = cached.get("refreshed_at")
        items = cached.get("items") if isinstance(cached.get("items"), list) else []
        stale = _is_stale(refreshed_at)
        return {"items": items, "refreshed_at": refreshed_at, "stale": stale}
    raw = _fetch_account_positions(session, mode)
    if raw:
        symbols = [str(item.get("symbol") or "").strip().upper() for item in raw]
        snapshots = fetch_market_snapshots(
            session,
            symbols=[symbol for symbol in symbols if symbol],
            store=False,
            fallback_history=True,
            history_duration="5 D",
            history_bar_size="1 day",
            history_use_rth=True,
        )
        snapshot_map = {item.get("symbol"): item for item in snapshots}
        merged = _merge_position_prices(raw, snapshot_map)
        refreshed_at = datetime.utcnow()
        write_cached_positions(cache_path, merged, refreshed_at)
        return {"items": merged, "refreshed_at": refreshed_at.isoformat(), "stale": False}
    if cached:
        refreshed_at = cached.get("refreshed_at")
        items = cached.get("items") if isinstance(cached.get("items"), list) else []
        return {"items": items, "refreshed_at": refreshed_at, "stale": True}
    return {"items": [], "refreshed_at": None, "stale": True}


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
