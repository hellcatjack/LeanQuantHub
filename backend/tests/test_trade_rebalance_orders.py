from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_order_builder import build_rebalance_orders


def _by_symbol_side(orders):
    return {(o["symbol"], o["side"]): o for o in orders}


def test_build_rebalance_orders_includes_liquidations():
    orders = build_rebalance_orders(
        target_weights={"AAA": 0.1},
        current_positions={"AAA": 0.0, "BBB": 5.0},
        price_map={"AAA": 100.0, "BBB": 50.0},
        portfolio_value=1000.0,
        order_type="MKT",
    )
    mapped = _by_symbol_side(orders)
    assert ("AAA", "BUY") in mapped
    assert ("BBB", "SELL") in mapped
    assert mapped[("AAA", "BUY")]["quantity"] == 1
    assert mapped[("BBB", "SELL")]["quantity"] == 5


def test_build_rebalance_orders_sells_when_overweight():
    orders = build_rebalance_orders(
        target_weights={"AAA": 0.1},
        current_positions={"AAA": 3.0},
        price_map={"AAA": 50.0},
        portfolio_value=1000.0,
        order_type="MKT",
    )
    mapped = _by_symbol_side(orders)
    assert ("AAA", "SELL") in mapped
    assert mapped[("AAA", "SELL")]["quantity"] == 1


def test_build_rebalance_orders_skips_when_already_at_target():
    orders = build_rebalance_orders(
        target_weights={"AAA": 0.1},
        current_positions={"AAA": 2.0},
        price_map={"AAA": 50.0},
        portfolio_value=1000.0,
        order_type="MKT",
    )
    assert orders == []

