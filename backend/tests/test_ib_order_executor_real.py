from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ib_order_executor import IBOrderExecutor


def test_ib_order_executor_calls_real_submit(monkeypatch):
    monkeypatch.setattr("app.services.ib_order_executor.resolve_ib_api_mode", lambda _s: "ib")
    called = {"ok": False}

    def _submit_real(*_a, **_k):
        called["ok"] = True
        return {"filled": 0, "rejected": 0}

    monkeypatch.setattr("app.services.ib_order_executor.submit_orders_real", _submit_real)
    executor = IBOrderExecutor(settings_row=SimpleNamespace())
    executor.submit_orders(SimpleNamespace(), [])
    assert called["ok"] is True
