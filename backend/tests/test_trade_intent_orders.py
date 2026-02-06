from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_order_builder import build_intent_orders


def test_build_intent_orders_uses_weight_sign():
    items = [
        {"symbol": "AAPL", "weight": 0.02},
        {"symbol": "MSFT", "weight": -0.01},
    ]
    orders = build_intent_orders(items)
    assert orders[0]["side"] == "BUY"
    assert orders[1]["side"] == "SELL"
