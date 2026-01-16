from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_order_builder import build_orders


def test_build_orders_rounding():
    items = [
        {"symbol": "AAA", "weight": 0.2},
        {"symbol": "BBB", "weight": 0.1},
    ]
    price_map = {"AAA": 50.0, "BBB": 33.0}
    orders = build_orders(
        items,
        price_map=price_map,
        portfolio_value=10000,
        cash_buffer_ratio=0.1,
        lot_size=1,
    )
    assert len(orders) == 2
    assert orders[0]["symbol"] == "AAA"
    assert orders[0]["quantity"] == 36  # 10000*0.9*0.2/50
