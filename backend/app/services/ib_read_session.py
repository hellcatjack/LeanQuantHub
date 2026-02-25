from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

from app.core.config import settings


_REQUEST_TIMEOUT_MIN_SECONDS = 0.3
_INFO_ERROR_CODES = {2104, 2106, 2107, 2108, 2158}
_SESSION_REGISTRY_LOCK = Lock()
_SESSION_REGISTRY: dict[str, "IBReadSession"] = {}
_MAX_IB_CLIENT_ID = 2_147_483_647
_TRANSIENT_FALLBACK_STATE_LOCK = Lock()
_TRANSIENT_FALLBACK_STATE: dict[str, tuple[int, float]] = {}
_TRANSIENT_FALLBACK_ENABLED = bool(getattr(settings, "ib_transient_fallback_enabled", True))
_TRANSIENT_FALLBACK_BASE_BACKOFF_SECONDS = max(
    float(getattr(settings, "ib_transient_fallback_backoff_base_seconds", 60.0) or 60.0),
    1.0,
)
_TRANSIENT_FALLBACK_MAX_BACKOFF_SECONDS = max(
    float(getattr(settings, "ib_transient_fallback_backoff_max_seconds", 180.0) or 180.0),
    _TRANSIENT_FALLBACK_BASE_BACKOFF_SECONDS,
)
_TRANSIENT_PURPOSE_OFFSETS = {
    "positions": 1001,
    "summary": 1002,
    "pnl": 1003,
    "executions": 1004,
    "completed_orders": 1005,
}


def _normalize_mode(mode: str | None) -> str:
    value = str(mode or "").strip().lower()
    if value == "live":
        return "live"
    return "paper"


def _resolve_client_id(*, mode: str, client_id_hint: int | None = None) -> int:
    if client_id_hint is not None:
        try:
            hinted = int(client_id_hint)
        except (TypeError, ValueError):
            hinted = 0
        if hinted > 0:
            return hinted
    if mode == "live":
        return int(getattr(settings, "ib_read_session_client_id_live", 180000201) or 180000201)
    return int(getattr(settings, "ib_read_session_client_id_paper", 180000101) or 180000101)


def _normalize_port(value: object) -> int:
    try:
        port = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return port if port > 0 else 0


def _resolve_transient_fallback_key(*, mode: str, host: str, port: int, purpose: str) -> str:
    return "|".join(
        (
            _normalize_mode(mode),
            str(host or "").strip(),
            str(_normalize_port(port)),
            str(purpose or "").strip().lower(),
        )
    )


def can_attempt_ib_transient_fallback(
    *,
    mode: str,
    host: str,
    port: int,
    purpose: str,
) -> bool:
    if not _TRANSIENT_FALLBACK_ENABLED:
        return False
    now_mono = monotonic()
    key = _resolve_transient_fallback_key(mode=mode, host=host, port=port, purpose=purpose)
    with _TRANSIENT_FALLBACK_STATE_LOCK:
        state = _TRANSIENT_FALLBACK_STATE.get(key)
        if not isinstance(state, tuple):
            return True
        _failures, retry_after_mono = state
        return now_mono >= float(retry_after_mono)


def record_ib_transient_fallback_result(
    *,
    mode: str,
    host: str,
    port: int,
    purpose: str,
    success: bool,
) -> None:
    key = _resolve_transient_fallback_key(mode=mode, host=host, port=port, purpose=purpose)
    now_mono = monotonic()
    with _TRANSIENT_FALLBACK_STATE_LOCK:
        if success:
            _TRANSIENT_FALLBACK_STATE.pop(key, None)
            return
        failures = 1
        state = _TRANSIENT_FALLBACK_STATE.get(key)
        if isinstance(state, tuple):
            try:
                failures = max(1, int(state[0]) + 1)
            except Exception:
                failures = 1
        delay = _TRANSIENT_FALLBACK_BASE_BACKOFF_SECONDS * (2 ** (failures - 1))
        delay = min(delay, _TRANSIENT_FALLBACK_MAX_BACKOFF_SECONDS)
        _TRANSIENT_FALLBACK_STATE[key] = (failures, now_mono + float(delay))


def resolve_ib_transient_client_id(*, mode: str, purpose: str) -> int:
    normalized_mode = _normalize_mode(mode)
    base = _resolve_client_id(mode=normalized_mode, client_id_hint=None)
    offset = _TRANSIENT_PURPOSE_OFFSETS.get(str(purpose or "").strip().lower(), 1099)
    candidate = int(base) + int(offset)
    if candidate > _MAX_IB_CLIENT_ID:
        candidate = max(1, _MAX_IB_CLIENT_ID - int(offset))
    return candidate


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _create_ibapi_app():
    try:
        from ibapi.client import EClient
        from ibapi.wrapper import EWrapper
    except Exception:
        return None

    class _App(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)
            self.ready = Event()
            self._request_lock = Lock()
            self._next_req_id = 9_500_000
            self._positions_event: Event | None = None
            self._positions_rows: list[dict[str, object]] = []
            self._summary_requests: dict[int, dict[str, Any]] = {}
            self._pnl_requests: dict[int, dict[str, Any]] = {}
            self._execution_requests: dict[int, dict[str, Any]] = {}
            self._completed_event: Event | None = None
            self._completed_rows: list[dict[str, object]] = []

        def nextValidId(self, _order_id: int):
            self.ready.set()

        def connectionClosed(self):
            self.ready.clear()

        def _alloc_req_id(self) -> int:
            with self._request_lock:
                self._next_req_id += 1
                return self._next_req_id

        def begin_positions_request(self) -> Event:
            with self._request_lock:
                event = Event()
                self._positions_event = event
                self._positions_rows = []
                return event

        def end_positions_request(self) -> list[dict[str, object]]:
            with self._request_lock:
                rows = list(self._positions_rows)
                self._positions_rows = []
                self._positions_event = None
                return rows

        def begin_summary_request(self, *, account_id: str | None) -> tuple[int, Event]:
            req_id = self._alloc_req_id()
            with self._request_lock:
                event = Event()
                self._summary_requests[req_id] = {
                    "event": event,
                    "rows": [],
                    "account_id": str(account_id or "").strip().upper() or None,
                }
                return req_id, event

        def end_summary_request(self, req_id: int) -> list[dict[str, object]]:
            with self._request_lock:
                state = self._summary_requests.pop(int(req_id), None)
                if not isinstance(state, dict):
                    return []
                return list(state.get("rows") or [])

        def begin_pnl_request(self) -> tuple[int, Event]:
            req_id = self._alloc_req_id()
            with self._request_lock:
                event = Event()
                self._pnl_requests[req_id] = {
                    "event": event,
                    "payload": {},
                }
                return req_id, event

        def end_pnl_request(self, req_id: int) -> dict[str, float]:
            with self._request_lock:
                state = self._pnl_requests.pop(int(req_id), None)
                if not isinstance(state, dict):
                    return {}
                payload = state.get("payload")
                return dict(payload) if isinstance(payload, dict) else {}

        def begin_execution_request(self) -> tuple[int, Event]:
            req_id = self._alloc_req_id()
            with self._request_lock:
                event = Event()
                self._execution_requests[req_id] = {
                    "event": event,
                    "rows": [],
                }
                return req_id, event

        def end_execution_request(self, req_id: int) -> list[dict[str, object]]:
            with self._request_lock:
                state = self._execution_requests.pop(int(req_id), None)
                if not isinstance(state, dict):
                    return []
                return list(state.get("rows") or [])

        def begin_completed_orders_request(self) -> Event:
            with self._request_lock:
                event = Event()
                self._completed_event = event
                self._completed_rows = []
                return event

        def end_completed_orders_request(self) -> list[dict[str, object]]:
            with self._request_lock:
                rows = list(self._completed_rows)
                self._completed_rows = []
                self._completed_event = None
                return rows

        def _signal_on_error(self, req_id: int, error_code: int):
            if int(error_code) in _INFO_ERROR_CODES:
                return
            with self._request_lock:
                summary_state = self._summary_requests.get(int(req_id))
                if isinstance(summary_state, dict):
                    event = summary_state.get("event")
                    if isinstance(event, Event):
                        event.set()
                pnl_state = self._pnl_requests.get(int(req_id))
                if isinstance(pnl_state, dict):
                    event = pnl_state.get("event")
                    if isinstance(event, Event):
                        event.set()
                execution_state = self._execution_requests.get(int(req_id))
                if isinstance(execution_state, dict):
                    event = execution_state.get("event")
                    if isinstance(event, Event):
                        event.set()

        def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
            try:
                req_id = int(reqId)
                code = int(errorCode)
            except Exception:
                return
            self._signal_on_error(req_id, code)

        def position(self, account, contract, pos, avgCost):
            with self._request_lock:
                if self._positions_event is None:
                    return
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
                self._positions_rows.append(
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
            with self._request_lock:
                if self._positions_event is not None:
                    self._positions_event.set()

        def accountSummary(self, reqId, account, tag, value, currency):
            req_id = int(reqId)
            with self._request_lock:
                state = self._summary_requests.get(req_id)
                if not isinstance(state, dict):
                    return
                target_account = state.get("account_id")
                account_text = str(account or "").strip()
                if target_account and account_text and account_text.upper() != target_account:
                    return
                rows = state.get("rows")
                if not isinstance(rows, list):
                    return
                rows.append(
                    {
                        "name": str(tag or "").strip(),
                        "value": value,
                        "currency": str(currency or "").strip().upper(),
                        "account": account_text or None,
                    }
                )

        def accountSummaryEnd(self, reqId):
            req_id = int(reqId)
            with self._request_lock:
                state = self._summary_requests.get(req_id)
                if not isinstance(state, dict):
                    return
                event = state.get("event")
                if isinstance(event, Event):
                    event.set()

        def pnl(self, reqId, dailyPnL, unrealizedPnL, realizedPnL):
            req_id = int(reqId)
            with self._request_lock:
                state = self._pnl_requests.get(req_id)
                if not isinstance(state, dict):
                    return
                payload = state.get("payload")
                if not isinstance(payload, dict):
                    payload = {}
                    state["payload"] = payload
                for key, raw_value in (
                    ("UnrealizedPnL", unrealizedPnL),
                    ("RealizedPnL", realizedPnL),
                    ("DailyPnL", dailyPnL),
                ):
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    if value != value or abs(value) >= 1e100:
                        continue
                    payload[key] = value
                event = state.get("event")
                if isinstance(event, Event) and payload:
                    event.set()

        def execDetails(self, reqId, contract, execution):
            req_id = int(reqId)
            with self._request_lock:
                state = self._execution_requests.get(req_id)
                if not isinstance(state, dict):
                    return
                rows = state.get("rows")
                if not isinstance(rows, list):
                    return
                try:
                    order_id = int(getattr(execution, "orderId", 0) or 0)
                except (TypeError, ValueError):
                    order_id = 0
                exec_id = str(getattr(execution, "execId", "") or "").strip()
                if order_id <= 0 or not exec_id:
                    return
                rows.append(
                    {
                        "order_id": order_id,
                        "symbol": str(getattr(contract, "symbol", "") or "").strip().upper(),
                        "side": str(getattr(execution, "side", "") or "").strip(),
                        "shares": float(getattr(execution, "shares", 0.0) or 0.0),
                        "price": float(getattr(execution, "price", 0.0) or 0.0),
                        "exec_id": exec_id,
                        "time_raw": str(getattr(execution, "time", "") or "").strip(),
                    }
                )

        def execDetailsEnd(self, reqId):
            req_id = int(reqId)
            with self._request_lock:
                state = self._execution_requests.get(req_id)
                if not isinstance(state, dict):
                    return
                event = state.get("event")
                if isinstance(event, Event):
                    event.set()

        def completedOrder(self, contract, order, orderState):
            with self._request_lock:
                if self._completed_event is None:
                    return
                try:
                    row = {
                        "order_id": int(getattr(order, "orderId", 0) or 0),
                        "perm_id": int(getattr(order, "permId", 0) or 0),
                        "symbol": str(getattr(contract, "symbol", "") or "").strip().upper(),
                        "side": str(getattr(order, "action", "") or "").strip(),
                        "status": str(getattr(orderState, "status", "") or "").strip(),
                        "completed_time_raw": str(getattr(orderState, "completedTime", "") or "").strip(),
                        "order_ref": str(getattr(order, "orderRef", "") or "").strip(),
                        "completed_status": str(getattr(orderState, "completedStatus", "") or "").strip(),
                    }
                except Exception:
                    return
                if row["order_id"] <= 0 and not row["order_ref"]:
                    return
                self._completed_rows.append(row)

        def completedOrdersEnd(self):
            with self._request_lock:
                if self._completed_event is not None:
                    self._completed_event.set()

    return _App()


class IBReadSession:
    def __init__(self, *, mode: str, host: str, port: int, client_id: int):
        self.mode = _normalize_mode(mode)
        self.host = str(host or "").strip()
        self.port = _normalize_port(port)
        self.client_id = int(client_id)
        self._connect_lock = Lock()
        self._request_lock = Lock()
        self._app = None
        self._thread: Thread | None = None
        self._closed = False

    def matches_endpoint(self, *, mode: str, host: str, port: int, client_id: int) -> bool:
        return (
            self.mode == _normalize_mode(mode)
            and self.host == str(host or "").strip()
            and self.port == _normalize_port(port)
            and self.client_id == int(client_id)
        )

    def _disconnect_locked(self) -> None:
        app = self._app
        thread = self._thread
        self._app = None
        self._thread = None
        if app is not None:
            try:
                app.disconnect()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=0.2)

    def _disconnect(self) -> None:
        with self._connect_lock:
            self._disconnect_locked()

    def close(self) -> None:
        self._closed = True
        self._disconnect()

    def _ensure_connected(self, *, timeout_seconds: float) -> bool:
        timeout = max(_REQUEST_TIMEOUT_MIN_SECONDS, float(timeout_seconds))
        if self._closed or not self.host or self.port <= 0:
            return False
        with self._connect_lock:
            app = self._app
            if app is not None and bool(getattr(app, "isConnected", lambda: False)()) and app.ready.is_set():
                return True
            self._disconnect_locked()
            app = _create_ibapi_app()
            if app is None:
                return False
            thread: Thread | None = None
            try:
                app.connect(self.host, int(self.port), int(self.client_id))
                thread = Thread(target=app.run, daemon=True)
                thread.start()
                if not app.ready.wait(timeout):
                    try:
                        app.disconnect()
                    except Exception:
                        pass
                    if thread is not None:
                        thread.join(timeout=0.2)
                    return False
                self._app = app
                self._thread = thread
                return True
            except Exception:
                try:
                    app.disconnect()
                except Exception:
                    pass
                if thread is not None:
                    thread.join(timeout=0.2)
                self._app = None
                self._thread = None
                return False

    def _run_request(self, callback, *, timeout_seconds: float):
        timeout = max(_REQUEST_TIMEOUT_MIN_SECONDS, float(timeout_seconds))
        with self._request_lock:
            if not self._ensure_connected(timeout_seconds=timeout):
                return None
            app = self._app
            if app is None:
                return None
            try:
                return callback(app, timeout)
            except Exception:
                self._disconnect()
                return None

    def fetch_positions(self, *, timeout_seconds: float = 6.0) -> list[dict[str, object]] | None:
        def _callback(app, timeout):
            event = app.begin_positions_request()
            rows: list[dict[str, object]] | None = None
            try:
                app.reqPositions()
                if not event.wait(timeout):
                    return None
                rows = app.end_positions_request()
                rows.sort(key=lambda item: str(item.get("symbol") or ""))
                return rows
            finally:
                if rows is None:
                    app.end_positions_request()
                try:
                    app.cancelPositions()
                except Exception:
                    pass

        return self._run_request(_callback, timeout_seconds=timeout_seconds)

    def fetch_account_summary(
        self,
        *,
        tags: tuple[str, ...],
        account_id: str | None,
        timeout_seconds: float = 6.0,
    ) -> list[dict[str, object]] | None:
        tags_clean = tuple(str(tag or "").strip() for tag in tags if str(tag or "").strip())
        if not tags_clean:
            return None

        def _callback(app, timeout):
            req_id, event = app.begin_summary_request(account_id=account_id)
            rows: list[dict[str, object]] | None = None
            try:
                app.reqAccountSummary(req_id, "All", ",".join(tags_clean))
                if not event.wait(timeout):
                    return None
                rows = app.end_summary_request(req_id)
                return [item for item in rows if str(item.get("name") or "").strip()]
            finally:
                if rows is None:
                    app.end_summary_request(req_id)
                try:
                    app.cancelAccountSummary(req_id)
                except Exception:
                    pass

        return self._run_request(_callback, timeout_seconds=timeout_seconds)

    def fetch_account_pnl(
        self,
        *,
        account_id: str,
        timeout_seconds: float = 6.0,
    ) -> dict[str, float] | None:
        account_text = str(account_id or "").strip()
        if not account_text:
            return None

        def _callback(app, timeout):
            req_id, event = app.begin_pnl_request()
            payload: dict[str, float] | None = None
            try:
                app.reqPnL(req_id, account_text, "")
                if not event.wait(timeout):
                    return None
                payload = app.end_pnl_request(req_id)
                return payload if payload else None
            finally:
                if payload is None:
                    app.end_pnl_request(req_id)
                try:
                    app.cancelPnL(req_id)
                except Exception:
                    pass

        return self._run_request(_callback, timeout_seconds=timeout_seconds)

    def fetch_executions(
        self,
        *,
        start_time_utc: datetime,
        timeout_seconds: float = 6.0,
    ) -> list[dict[str, object]] | None:
        try:
            from ibapi.execution import ExecutionFilter
        except Exception:
            return None

        if start_time_utc.tzinfo is None:
            start_utc = start_time_utc.replace(tzinfo=timezone.utc)
        else:
            start_utc = start_time_utc.astimezone(timezone.utc)
        start_local = start_utc.astimezone(_local_timezone())

        def _callback(app, timeout):
            req_id, event = app.begin_execution_request()
            rows: list[dict[str, object]] | None = None
            try:
                execution_filter = ExecutionFilter()
                execution_filter.time = start_local.strftime("%Y%m%d %H:%M:%S")
                app.reqExecutions(req_id, execution_filter)
                if not event.wait(timeout):
                    return None
                rows = app.end_execution_request(req_id)
                return rows
            finally:
                if rows is None:
                    app.end_execution_request(req_id)

        return self._run_request(_callback, timeout_seconds=timeout_seconds)

    def fetch_completed_orders(self, *, timeout_seconds: float = 6.0) -> list[dict[str, object]] | None:
        def _callback(app, timeout):
            event = app.begin_completed_orders_request()
            rows: list[dict[str, object]] | None = None
            try:
                app.reqCompletedOrders(False)
                if not event.wait(timeout):
                    return None
                rows = app.end_completed_orders_request()
                return rows
            finally:
                if rows is None:
                    app.end_completed_orders_request()

        return self._run_request(_callback, timeout_seconds=timeout_seconds)


def get_ib_read_session(
    *,
    mode: str,
    host: str,
    port: int,
    client_id_hint: int | None = None,
) -> IBReadSession | None:
    if not bool(getattr(settings, "ib_read_session_enabled", True)):
        return None
    host_text = str(host or "").strip()
    port_value = _normalize_port(port)
    if not host_text or port_value <= 0:
        return None

    mode_key = _normalize_mode(mode)
    client_id = _resolve_client_id(mode=mode_key, client_id_hint=client_id_hint)
    with _SESSION_REGISTRY_LOCK:
        existing = _SESSION_REGISTRY.get(mode_key)
        if existing is not None and existing.matches_endpoint(
            mode=mode_key,
            host=host_text,
            port=port_value,
            client_id=client_id,
        ):
            return existing
        if existing is not None:
            existing.close()
        created = IBReadSession(
            mode=mode_key,
            host=host_text,
            port=port_value,
            client_id=client_id,
        )
        _SESSION_REGISTRY[mode_key] = created
        return created


def reset_ib_read_sessions() -> None:
    with _SESSION_REGISTRY_LOCK:
        sessions = list(_SESSION_REGISTRY.values())
        _SESSION_REGISTRY.clear()
    for session in sessions:
        try:
            session.close()
        except Exception:
            continue
    with _TRANSIENT_FALLBACK_STATE_LOCK:
        _TRANSIENT_FALLBACK_STATE.clear()
