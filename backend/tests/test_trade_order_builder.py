from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_order_builder import build_orders


def test_build_orders_min_qty_ceil_prevents_zero():
    items = [{"symbol": "KLAC", "weight": 0.0005}]
    price_map = {"KLAC": 1000.0}
    orders = build_orders(items, price_map=price_map, portfolio_value=1000.0)
    assert len(orders) == 1
    assert orders[0]["quantity"] == 1


def test_build_orders_respects_lot_size_with_ceil():
    items = [{"symbol": "ABC", "weight": 0.0005}]
    price_map = {"ABC": 100.0}
    orders = build_orders(
        items,
        price_map=price_map,
        portfolio_value=1000.0,
        lot_size=10,
    )
    assert len(orders) == 1
    assert orders[0]["quantity"] == 10
