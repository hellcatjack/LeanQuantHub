from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ib_execution import IBExecutionClient, ExecutionEvent


def test_ib_execution_client_returns_events(monkeypatch):
    client = IBExecutionClient("127.0.0.1", 7497, 101)
    expected = [ExecutionEvent(order_id=1, status="SUBMITTED", exec_id=None, filled=0, avg_price=None)]
    monkeypatch.setattr(client, "_submit_orders", lambda orders: expected)
    events = client.submit_orders([object()])
    assert events == expected
