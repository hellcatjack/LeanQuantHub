from __future__ import annotations

from dataclasses import dataclass
import threading
import time

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order
    _IBAPI_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    EClient = object  # type: ignore[assignment]
    EWrapper = object  # type: ignore[assignment]
    Contract = object  # type: ignore[assignment]
    Order = object  # type: ignore[assignment]
    _IBAPI_AVAILABLE = False


@dataclass
class ExecutionEvent:
    order_id: int
    status: str
    exec_id: str | None
    filled: float
    avg_price: float | None


class _ExecutionClient(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, timeout: float = 5.0) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._ready = threading.Event()
        self._error: str | None = None
        self._next_id: int | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self._next_id = int(orderId)
        self._ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):  # type: ignore[override]  # noqa: N802
        if errorCode in {502, 503, 504, 1100, 1101, 1102}:
            self._error = f"{errorCode}:{errorString}"
            self._ready.set()


class IBExecutionClient:
    def __init__(self, host: str, port: int, client_id: int, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout

    def submit_orders(self, orders: list[object]) -> list[ExecutionEvent]:
        return self._submit_orders(orders)

    def _submit_orders(self, orders: list[object]) -> list[ExecutionEvent]:
        if not _IBAPI_AVAILABLE:
            raise RuntimeError("ibapi_not_available")
        client = _ExecutionClient(self.host, self.port, self.client_id, timeout=self.timeout)
        try:
            client.connect(self.host, int(self.port), int(self.client_id))
        except Exception as exc:  # pragma: no cover - network
            raise RuntimeError(f"ib_execution_connect_failed:{exc.__class__.__name__}") from exc
        thread = threading.Thread(target=client.run, daemon=True)
        thread.start()
        if not client._ready.wait(self.timeout):
            client.disconnect()
            raise RuntimeError("ib_execution_timeout")
        if client._error:
            client.disconnect()
            raise RuntimeError(f"ib_execution_error:{client._error}")
        if client._next_id is None:
            client.disconnect()
            raise RuntimeError("ib_execution_no_order_id")

        events: list[ExecutionEvent] = []
        next_id = client._next_id
        for order in orders:
            symbol = str(getattr(order, "symbol", "") or "").strip().upper()
            side = str(getattr(order, "side", "") or "").strip().upper() or "BUY"
            quantity = float(getattr(order, "quantity", 0) or 0)
            if not symbol or quantity <= 0:
                events.append(
                    ExecutionEvent(
                        order_id=next_id,
                        status="REJECTED",
                        exec_id=None,
                        filled=0.0,
                        avg_price=None,
                    )
                )
                next_id += 1
                continue
            contract = Contract()
            contract.symbol = symbol
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"
            ib_order = Order()
            ib_order.action = "BUY" if side != "SELL" else "SELL"
            ib_order.orderType = "MKT"
            ib_order.totalQuantity = quantity
            client.placeOrder(next_id, contract, ib_order)
            events.append(
                ExecutionEvent(
                    order_id=next_id,
                    status="SUBMITTED",
                    exec_id=None,
                    filled=0.0,
                    avg_price=None,
                )
            )
            next_id += 1

        time.sleep(0.1)
        client.disconnect()
        thread.join(timeout=1)
        return events
