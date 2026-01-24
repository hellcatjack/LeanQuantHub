from __future__ import annotations

import csv
import json
import os
import threading
import time
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
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

from app.core.config import settings
from app.models import IBContractCache
from app.services.job_lock import JobLock
from app.services.project_symbols import collect_active_project_symbols
from app.services.ib_settings import ensure_ib_client_id, resolve_ib_api_mode


_MARKET_DATA_TYPE_MAP = {
    "realtime": 1,
    "delayed": 3,
    "delayed_frozen": 4,
}

_IGNORE_ERROR_CODES = {10167, 2104, 2106, 2107, 2108, 2158, 2176}
_FATAL_ERROR_CODES = {502, 503, 504, 1100, 1101, 1102}

_PRICE_TICKS = {1: "bid", 2: "ask", 4: "last", 6: "high", 7: "low", 9: "close"}
_SIZE_TICKS = {0: "bid_size", 3: "ask_size", 5: "last_size", 8: "volume"}


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def _ib_data_root() -> Path:
    root = _resolve_data_root() / "ib"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _market_data_type_id(value: str | None) -> int:
    return _MARKET_DATA_TYPE_MAP.get((value or "").strip().lower(), 1)


def _build_contract(
    symbol: str,
    *,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
    con_id: int | None = None,
) -> Contract:
    contract = Contract()
    contract.symbol = _normalize_symbol(symbol)
    contract.secType = sec_type
    contract.exchange = exchange
    contract.currency = currency
    if primary_exchange:
        contract.primaryExchange = primary_exchange
    if con_id:
        contract.conId = con_id
    return contract


def _contract_details_to_dict(details: Any) -> dict[str, Any]:
    contract = details.contract
    return {
        "market_name": getattr(details, "marketName", None),
        "min_tick": getattr(details, "minTick", None),
        "long_name": getattr(details, "longName", None),
        "contract": {
            "con_id": getattr(contract, "conId", None),
            "symbol": getattr(contract, "symbol", None),
            "sec_type": getattr(contract, "secType", None),
            "exchange": getattr(contract, "exchange", None),
            "primary_exchange": getattr(contract, "primaryExchange", None),
            "currency": getattr(contract, "currency", None),
            "local_symbol": getattr(contract, "localSymbol", None),
            "multiplier": getattr(contract, "multiplier", None),
        },
    }


class IBRequestSession(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, timeout: float = 5.0) -> None:
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._req_lock = threading.Lock()
        self._req_id = 1
        self._pending: dict[int, threading.Event] = {}
        self._contract_details: dict[int, list[Any]] = {}
        self._market_data: dict[int, dict[str, Any]] = {}
        self._historical_bars: dict[int, list[dict[str, Any]]] = {}
        self._errors: dict[int, str] = {}
        self._connection_error: str | None = None

    def __enter__(self) -> "IBRequestSession":
        self.connect(self._host, self._port, self._client_id)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        if not self._ready.wait(self._timeout):
            raise RuntimeError("ib_connect_timeout")
        if self._connection_error:
            raise RuntimeError(self._connection_error)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.isConnected():
            self.disconnect()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _next_req_id(self) -> int:
        with self._req_lock:
            req_id = self._req_id
            self._req_id += 1
            return req_id

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self._ready.set()

    def error(  # noqa: N802
        self,
        reqId: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str | None = None,
    ) -> None:
        if errorCode in _IGNORE_ERROR_CODES:
            return
        message = f"{errorCode}:{errorString}"
        if errorCode in _FATAL_ERROR_CODES:
            self._connection_error = message
        if reqId in self._pending:
            self._errors[reqId] = message
            self._pending[reqId].set()

    def contractDetails(self, reqId: int, contractDetails) -> None:  # noqa: N802
        self._contract_details.setdefault(reqId, []).append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        if reqId in self._pending:
            self._pending[reqId].set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802
        key = _PRICE_TICKS.get(tickType)
        if key is None:
            return
        self._market_data.setdefault(reqId, {})[key] = price

    def tickSize(self, reqId: int, tickType: int, size: int) -> None:  # noqa: N802
        key = _SIZE_TICKS.get(tickType)
        if key is None:
            return
        self._market_data.setdefault(reqId, {})[key] = size

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802
        if reqId in self._pending:
            self._pending[reqId].set()

    def historicalData(self, reqId: int, bar) -> None:  # noqa: N802
        self._historical_bars.setdefault(reqId, []).append(
            {
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        if reqId in self._pending:
            self._pending[reqId].set()

    def request_contract_details(self, contract: Contract, timeout: float | None = None) -> tuple[list[Any], str | None]:
        req_id = self._next_req_id()
        event = threading.Event()
        self._pending[req_id] = event
        self.reqContractDetails(req_id, contract)
        event.wait(timeout or self._timeout)
        details = self._contract_details.pop(req_id, [])
        error = self._errors.pop(req_id, None)
        self._pending.pop(req_id, None)
        return details, error

    def request_market_snapshot(
        self,
        contract: Contract,
        market_data_type: int,
        regulatory_snapshot: bool = False,
        timeout: float | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        req_id = self._next_req_id()
        event = threading.Event()
        self._pending[req_id] = event
        self.reqMarketDataType(market_data_type)
        self.reqMktData(req_id, contract, "", True, regulatory_snapshot, [])
        event.wait(timeout or self._timeout)
        snapshot = self._market_data.pop(req_id, {})
        error = self._errors.pop(req_id, None)
        self._pending.pop(req_id, None)
        return snapshot, error

    def request_historical_data(
        self,
        contract: Contract,
        *,
        end_datetime: str | None,
        duration: str,
        bar_size: str,
        use_rth: bool,
        timeout: float | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        req_id = self._next_req_id()
        event = threading.Event()
        self._pending[req_id] = event
        end_value = end_datetime or ""
        self.reqHistoricalData(
            req_id,
            contract,
            end_value,
            duration,
            bar_size,
            "TRADES",
            1 if use_rth else 0,
            1,
            False,
            [],
        )
        event.wait(timeout or self._timeout)
        bars = self._historical_bars.pop(req_id, [])
        error = self._errors.pop(req_id, None)
        self._pending.pop(req_id, None)
        return bars, error


class IBMockAdapter:
    def __init__(self, data_root: Path | None = None) -> None:
        self._data_root = data_root or _ib_data_root()
        self._mock_root = self._data_root / "mock"
        self._contracts: dict[str, Any] = {}
        self._snapshots: dict[str, Any] = {}
        self._bars_dir = self._mock_root / "bars"

    def __enter__(self) -> "IBMockAdapter":
        self._mock_root.mkdir(parents=True, exist_ok=True)
        self._bars_dir.mkdir(parents=True, exist_ok=True)
        self._contracts = _load_mock_json(self._mock_root / "contracts.json")
        self._snapshots = _load_mock_json(self._mock_root / "snapshots.json")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def request_contract_details(
        self,
        symbol: str,
        sec_type: str,
        exchange: str,
        currency: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        symbol = _normalize_symbol(symbol)
        fixture = self._contracts.get(symbol)
        if isinstance(fixture, dict) and fixture.get("error"):
            return None, str(fixture.get("error"))
        if isinstance(fixture, dict) and fixture.get("contract"):
            return fixture, None
        detail = _mock_contract_detail(symbol, sec_type, exchange, currency)
        return detail, None

    def request_market_snapshot(
        self,
        symbol: str,
        *,
        market_data_type: int | None = None,
        regulatory_snapshot: bool | None = None,
        exchange: str | None = None,
        currency: str | None = None,
        primary_exchange: str | None = None,
        con_id: int | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        symbol = _normalize_symbol(symbol)
        fixture = self._snapshots.get(symbol)
        if isinstance(fixture, dict) and fixture.get("error"):
            return None, str(fixture.get("error"))
        if isinstance(fixture, dict) and fixture:
            payload = dict(fixture)
            payload.setdefault("timestamp", datetime.utcnow().isoformat(timespec="seconds"))
            return payload, None
        payload = _mock_snapshot(symbol)
        return payload, None

    def request_historical_data(
        self,
        symbol: str,
        *,
        end_datetime: str | None,
        duration: str,
        bar_size: str,
        use_rth: bool,
        exchange: str | None = None,
        currency: str | None = None,
        primary_exchange: str | None = None,
        con_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        symbol = _normalize_symbol(symbol)
        bars_path = self._bars_dir / f"{symbol}.csv"
        if bars_path.exists():
            bars = _read_bars_csv(bars_path)
            if bars:
                return bars, None
        bars = _mock_bars(bar_size)
        return bars, None


class IBLiveAdapter:
    def __init__(self, host: str, port: int, client_id: int, timeout: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._api: IBRequestSession | None = None

    def __enter__(self) -> "IBLiveAdapter":
        if not _IBAPI_AVAILABLE:
            raise RuntimeError("ibapi_not_available")
        self._api = IBRequestSession(self._host, self._port, self._client_id, timeout=self._timeout)
        self._api.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._api:
            self._api.__exit__(exc_type, exc, tb)

    def request_contract_details(
        self,
        symbol: str,
        sec_type: str,
        exchange: str,
        currency: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not self._api:
            return None, "ib_client_not_ready"
        contract = _build_contract(symbol, sec_type=sec_type, exchange=exchange, currency=currency)
        details_list, error = self._api.request_contract_details(contract, timeout=self._timeout)
        if error:
            return None, error
        if not details_list:
            return None, "no_contract_details"
        detail = _contract_details_to_dict(details_list[0])
        return detail, None

    def request_market_snapshot(
        self,
        symbol: str,
        *,
        market_data_type: int,
        regulatory_snapshot: bool,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
        con_id: int | None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not self._api:
            return None, "ib_client_not_ready"
        contract = _build_contract(
            symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
            con_id=con_id,
        )
        snapshot, error = self._api.request_market_snapshot(
            contract,
            market_data_type,
            regulatory_snapshot=regulatory_snapshot,
            timeout=self._timeout,
        )
        if error:
            return None, error
        return snapshot, None

    def request_historical_data(
        self,
        symbol: str,
        *,
        end_datetime: str | None,
        duration: str,
        bar_size: str,
        use_rth: bool,
        exchange: str,
        currency: str,
        primary_exchange: str | None,
        con_id: int | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not self._api:
            return [], "ib_client_not_ready"
        contract = _build_contract(
            symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
            con_id=con_id,
        )
        bars, error = self._api.request_historical_data(
            contract,
            end_datetime=end_datetime,
            duration=duration,
            bar_size=bar_size,
            use_rth=use_rth,
            timeout=self._timeout,
        )
        if error:
            return [], error
        return bars, None


def _load_mock_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _mock_con_id(symbol: str, sec_type: str, exchange: str, currency: str) -> int:
    payload = f"{symbol}:{sec_type}:{exchange}:{currency}"
    value = zlib.crc32(payload.encode("utf-8")) & 0x7FFFFFFF
    return value or 1


def _mock_contract_detail(
    symbol: str,
    sec_type: str,
    exchange: str,
    currency: str,
) -> dict[str, Any]:
    con_id = _mock_con_id(symbol, sec_type, exchange, currency)
    return {
        "market_name": "MOCK",
        "min_tick": 0.01,
        "long_name": f"{symbol} Mock Contract",
        "contract": {
            "con_id": con_id,
            "symbol": symbol,
            "sec_type": sec_type,
            "exchange": exchange,
            "primary_exchange": None,
            "currency": currency,
            "local_symbol": symbol,
            "multiplier": None,
        },
    }


def _mock_snapshot(symbol: str) -> dict[str, Any]:
    base = 100 + (zlib.crc32(symbol.encode("utf-8")) % 50)
    return {
        "bid": base - 0.1,
        "ask": base + 0.1,
        "last": base,
        "close": base,
        "volume": 1000000,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "source": "mock",
    }


def _bar_delta(bar_size: str) -> timedelta:
    value = str(bar_size or "").strip().lower()
    if "hour" in value:
        return timedelta(hours=1)
    if "min" in value:
        return timedelta(minutes=1)
    return timedelta(days=1)


def _mock_bars(bar_size: str, count: int = 5) -> list[dict[str, Any]]:
    delta = _bar_delta(bar_size)
    end = datetime.utcnow().replace(microsecond=0)
    bars: list[dict[str, Any]] = []
    for idx in range(count):
        stamp = end - delta * (count - 1 - idx)
        base = 100 + idx
        bars.append(
            {
                "date": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": base - 0.2,
                "high": base + 0.4,
                "low": base - 0.5,
                "close": base,
                "volume": 100000 + idx * 1000,
            }
        )
    return bars


def _read_bars_csv(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            bars = []
            for row in reader:
                bars.append(
                    {
                        "date": row.get("date"),
                        "open": float(row.get("open") or 0),
                        "high": float(row.get("high") or 0),
                        "low": float(row.get("low") or 0),
                        "close": float(row.get("close") or 0),
                        "volume": float(row.get("volume") or 0),
                    }
                )
            return bars
    except FileNotFoundError:
        return []


@contextmanager
def ib_request_lock(wait_seconds: float = 0.0, retry_interval: float = 0.2) -> Any:
    lock = JobLock("ib_request", _resolve_data_root())
    deadline = time.time() + wait_seconds if wait_seconds and wait_seconds > 0 else None
    interval = max(float(retry_interval), 0.01)
    while True:
        if lock.acquire():
            break
        if deadline is None or time.time() >= deadline:
            raise RuntimeError("ib_request_lock_busy")
        time.sleep(interval)
    try:
        yield
    finally:
        lock.release()


@contextmanager
def ib_adapter(settings_row, *, timeout: float = 5.0) -> Any:
    mode = resolve_ib_api_mode(settings_row)
    if mode == "mock":
        with IBMockAdapter() as adapter:
            yield adapter
        return
    for attempt in range(2):
        try:
            with IBLiveAdapter(
                settings_row.host,
                settings_row.port,
                settings_row.client_id,
                timeout=timeout,
            ) as adapter:
                yield adapter
            return
        except RuntimeError as exc:
            if str(exc) != "ib_connect_timeout" or attempt >= 1:
                raise
            time.sleep(2)


def refresh_contract_cache(
    session,
    *,
    symbols: list[str] | None,
    sec_type: str | None,
    exchange: str | None,
    currency: str | None,
    use_project_symbols: bool,
) -> dict[str, Any]:
    start = time.monotonic()
    settings_row = ensure_ib_client_id(session)
    if use_project_symbols and not symbols:
        symbols, _benchmarks = collect_active_project_symbols(session)
    symbols = [_normalize_symbol(item) for item in (symbols or []) if _normalize_symbol(item)]
    if not symbols:
        return {"total": 0, "updated": 0, "skipped": 0, "errors": ["symbols_empty"], "duration_sec": 0.0}
    sec_type = (sec_type or "STK").strip().upper()
    exchange = (exchange or "SMART").strip().upper()
    currency = (currency or "USD").strip().upper()
    errors: list[str] = []
    updated = 0
    skipped = 0
    with ib_request_lock():
        with ib_adapter(settings_row) as api:
            for symbol in symbols:
                detail, error = api.request_contract_details(symbol, sec_type, exchange, currency)
                if error:
                    errors.append(f"{symbol}:{error}")
                    skipped += 1
                    continue
                if not detail:
                    errors.append(f"{symbol}:no_contract_details")
                    skipped += 1
                    continue
                contract = detail.get("contract") or {}
                row = (
                    session.query(IBContractCache)
                    .filter(
                        IBContractCache.symbol == symbol,
                        IBContractCache.sec_type == sec_type,
                        IBContractCache.exchange == exchange,
                        IBContractCache.currency == currency,
                    )
                    .one_or_none()
                )
                con_id = int(contract.get("con_id") or 0)
                if row is None:
                    row = IBContractCache(
                        symbol=symbol,
                        sec_type=sec_type,
                        exchange=exchange,
                        currency=currency,
                        con_id=con_id,
                    )
                    session.add(row)
                row.primary_exchange = contract.get("primary_exchange") or None
                row.local_symbol = contract.get("local_symbol") or None
                row.multiplier = contract.get("multiplier") or None
                row.con_id = con_id
                row.detail = detail
                updated += 1
            session.commit()
    duration = time.monotonic() - start
    return {
        "total": len(symbols),
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "duration_sec": round(duration, 3),
    }


def fetch_market_snapshots(
    session,
    *,
    symbols: list[str],
    store: bool,
    market_data_type: str | None = None,
    fallback_history: bool = False,
    history_duration: str = "5 D",
    history_bar_size: str = "1 day",
    history_use_rth: bool = True,
) -> list[dict[str, Any]]:
    settings_row = ensure_ib_client_id(session)
    api_mode = resolve_ib_api_mode(settings_row)
    market_data_type_value = market_data_type or settings_row.market_data_type
    market_data_type = _market_data_type_id(market_data_type_value)
    use_regulatory_snapshot = bool(getattr(settings_row, "use_regulatory_snapshot", False))
    symbols = [_normalize_symbol(item) for item in symbols if _normalize_symbol(item)]
    results: list[dict[str, Any]] = []
    data_root = _ib_data_root() / "stream"
    data_root.mkdir(parents=True, exist_ok=True)
    with ib_request_lock():
        with ib_adapter(settings_row) as api:
            for symbol in symbols:
                cache = (
                    session.query(IBContractCache)
                    .filter(
                        IBContractCache.symbol == symbol,
                        IBContractCache.sec_type == "STK",
                        IBContractCache.exchange == "SMART",
                        IBContractCache.currency == "USD",
                    )
                    .one_or_none()
                )
                exchange = cache.exchange if cache else "SMART"
                currency = cache.currency if cache else "USD"
                primary_exchange = cache.primary_exchange if cache else None
                con_id = cache.con_id if cache else None
                snapshot, error = api.request_market_snapshot(
                    symbol,
                    market_data_type=market_data_type,
                    regulatory_snapshot=use_regulatory_snapshot,
                    exchange=exchange,
                    currency=currency,
                    primary_exchange=primary_exchange,
                    con_id=con_id,
                )
                payload = None
                if snapshot:
                    snapshot["timestamp"] = datetime.utcnow().isoformat(timespec="seconds")
                    if not snapshot.get("source"):
                        snapshot["source"] = "mock" if api_mode == "mock" else "ib_snapshot"
                    payload = snapshot
                    if store:
                        path = data_root / f"{symbol}.json"
                        path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
                if not payload and not error and fallback_history:
                    bars, history_error = api.request_historical_data(
                        symbol,
                        end_datetime=None,
                        duration=history_duration,
                        bar_size=history_bar_size,
                        use_rth=history_use_rth,
                        exchange=exchange,
                        currency=currency,
                        primary_exchange=primary_exchange,
                        con_id=con_id,
                    )
                    if history_error:
                        error = history_error
                    elif not bars:
                        error = "no_history_data"
                    else:
                        last_bar = bars[-1]
                        payload = {
                            "source": "history_fallback",
                            "bar_date": last_bar.get("date"),
                            "close": last_bar.get("close"),
                            "open": last_bar.get("open"),
                            "high": last_bar.get("high"),
                            "low": last_bar.get("low"),
                            "volume": last_bar.get("volume"),
                            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
                        }
                        if store:
                            path = data_root / f"{symbol}.json"
                            path.write_text(
                                json.dumps(payload, ensure_ascii=False),
                                encoding="utf-8",
                            )
                if not payload and not error:
                    error = "no_snapshot_data"
                results.append({"symbol": symbol, "data": payload, "error": error})
    return results


def fetch_historical_bars(
    session,
    *,
    symbol: str,
    duration: str,
    bar_size: str,
    end_datetime: str | None,
    use_rth: bool,
    store: bool,
) -> dict[str, Any]:
    settings_row = ensure_ib_client_id(session)
    symbol = _normalize_symbol(symbol)
    data_root = _ib_data_root() / "bars"
    data_root.mkdir(parents=True, exist_ok=True)
    with ib_request_lock():
        with ib_adapter(settings_row) as api:
            cache = (
                session.query(IBContractCache)
                .filter(
                    IBContractCache.symbol == symbol,
                    IBContractCache.sec_type == "STK",
                    IBContractCache.exchange == "SMART",
                    IBContractCache.currency == "USD",
                )
                .one_or_none()
            )
            exchange = cache.exchange if cache else "SMART"
            currency = cache.currency if cache else "USD"
            primary_exchange = cache.primary_exchange if cache else None
            con_id = cache.con_id if cache else None
            bars, error = api.request_historical_data(
                symbol,
                end_datetime=end_datetime,
                duration=duration,
                bar_size=bar_size,
                use_rth=use_rth,
                exchange=exchange,
                currency=currency,
                primary_exchange=primary_exchange,
                con_id=con_id,
            )
    path = None
    if store and bars:
        path = data_root / f"{symbol}.csv"
        write_bars_csv(path, bars)
    return {
        "symbol": symbol,
        "bars": len(bars),
        "path": str(path) if path else None,
        "error": error,
    }


def write_bars_csv(path: Path, bars: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow(
                [
                    bar.get("date"),
                    bar.get("open"),
                    bar.get("high"),
                    bar.get("low"),
                    bar.get("close"),
                    bar.get("volume"),
                ]
            )
    tmp_path.replace(path)


def check_market_health(
    session,
    *,
    symbols: list[str],
    min_success_ratio: float,
    fallback_history: bool,
    history_duration: str,
    history_bar_size: str,
    history_use_rth: bool,
) -> dict[str, Any]:
    items = fetch_market_snapshots(
        session,
        symbols=symbols,
        store=False,
        fallback_history=fallback_history,
        history_duration=history_duration,
        history_bar_size=history_bar_size,
        history_use_rth=history_use_rth,
    )
    missing_symbols: list[str] = []
    errors: list[str] = []
    for item in items:
        symbol = item.get("symbol") or ""
        if item.get("error") or not item.get("data"):
            missing_symbols.append(symbol)
            if item.get("error"):
                errors.append(f"{symbol}:{item['error']}")
    total = len(items)
    success = total - len(missing_symbols)
    ratio = success / total if total else 0.0
    status = "ok" if ratio >= min_success_ratio else "blocked"
    return {
        "status": status,
        "total": total,
        "success": success,
        "missing_symbols": missing_symbols,
        "errors": errors,
    }
