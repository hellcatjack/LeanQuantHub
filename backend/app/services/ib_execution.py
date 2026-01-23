from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order
except Exception:  # pragma: no cover - optional dependency
    EClient = object  # type: ignore[assignment]
    EWrapper = object  # type: ignore[assignment]
    Contract = object  # type: ignore[assignment]
    Order = object  # type: ignore[assignment]


@dataclass
class ExecutionEventBuffer:
    order_statuses: dict[int, str] = field(default_factory=dict)
    executions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def on_order_status(self, order_id: int, status: str, **kwargs: Any) -> None:
        payload = {"status": status}
        payload.update(kwargs)
        self.order_statuses[order_id] = status
        if order_id not in self.executions and payload:
            self.executions.setdefault(str(order_id), payload)

    def on_execution(
        self,
        exec_id: str,
        order_id: int,
        qty: float,
        price: float,
        **kwargs: Any,
    ) -> None:
        payload = {"order_id": order_id, "qty": qty, "price": price}
        payload.update(kwargs)
        self.executions[exec_id] = payload


class IBExecutionClient(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int) -> None:
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._buffer = ExecutionEventBuffer()
        self._connected_at: datetime | None = None

    def connect_and_start(self) -> None:
        self.connect(self._host, int(self._port), int(self._client_id))
        self._connected_at = datetime.utcnow()

    def submit_mkt_order(self, symbol: str, qty: float, side: str, client_order_id: str) -> int:
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        order = Order()
        order.action = side.upper()
        order.orderType = "MKT"
        order.totalQuantity = float(qty)
        order.orderRef = client_order_id
        order_id = self.nextOrderId()
        self.placeOrder(order_id, contract, order)
        return order_id

    def wait_for_updates(self, timeout_seconds: int) -> ExecutionEventBuffer:
        return self._buffer

    # IB callbacks
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):  # noqa: N802
        self._buffer.on_order_status(
            order_id=int(orderId),
            status=str(status),
            filled=float(filled or 0),
            remaining=float(remaining or 0),
            avg_fill_price=float(avgFillPrice or 0),
            perm_id=int(permId or 0),
            last_fill_price=float(lastFillPrice or 0),
            client_id=int(clientId or 0),
            why_held=whyHeld,
            mkt_cap_price=float(mktCapPrice or 0),
        )

    def execDetails(self, reqId, contract, execution):  # noqa: N802
        exec_id = getattr(execution, "execId", None)
        if not exec_id:
            return
        self._buffer.on_execution(
            exec_id=str(exec_id),
            order_id=int(getattr(execution, "orderId", 0) or 0),
            qty=float(getattr(execution, "shares", 0) or 0),
            price=float(getattr(execution, "price", 0) or 0),
            exchange=getattr(execution, "exchange", None),
            time=getattr(execution, "time", None),
            perm_id=int(getattr(execution, "permId", 0) or 0),
        )
