from pathlib import Path
import sys
import threading
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ib_execution


def test_submit_orders_collects_exec_events(monkeypatch):
    class FakeClient:
        def __init__(self, host, port, client_id, timeout=5.0):
            self._ready = threading.Event()
            self._ready.set()
            self._error = None
            self._next_id = 100
            self._events = []

        def connect(self, host, port, client_id):
            return None

        def run(self):
            return None

        def disconnect(self):
            return None

        def placeOrder(self, order_id, contract, order):
            self._events.append(
                ib_execution.ExecutionEvent(
                    order_id=order_id,
                    status="FILLED",
                    exec_id="X1",
                    filled=float(getattr(order, "totalQuantity", 0) or 0),
                    avg_price=10.5,
                    ib_order_id=order_id,
                )
            )

    monkeypatch.setattr(ib_execution, "_IBAPI_AVAILABLE", True)
    monkeypatch.setattr(ib_execution, "_ExecutionClient", FakeClient)
    monkeypatch.setattr(ib_execution, "Contract", SimpleNamespace)
    monkeypatch.setattr(ib_execution, "Order", SimpleNamespace)

    client = ib_execution.IBExecutionClient("127.0.0.1", 4001, 1)
    order = SimpleNamespace(id=1, symbol="SPY", side="BUY", quantity=1)
    events = client._submit_orders([order])
    assert events[0].status == "FILLED"
    assert events[0].exec_id == "X1"
