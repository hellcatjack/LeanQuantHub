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


def test_build_rebalance_orders_skips_sub_lot_reduction_to_avoid_crossing_target():
    # target_qty = ceil(0.1 * 1000 / 10) = 10
    # current is 10.6, delta is -0.6 (< lot=1), so it should be skipped.
    orders = build_rebalance_orders(
        target_weights={"AAA": 0.1},
        current_positions={"AAA": 10.6},
        price_map={"AAA": 10.0},
        portfolio_value=1000.0,
        lot_size=1,
        order_type="MKT",
    )
    assert orders == []


def test_build_rebalance_orders_reduces_only_full_lots_without_crossing_target():
    # target_qty = 10, current is 11.6, delta is -1.6.
    # With lot=1, only 1 share is tradable without crossing below target.
    orders = build_rebalance_orders(
        target_weights={"AAA": 0.1},
        current_positions={"AAA": 11.6},
        price_map={"AAA": 10.0},
        portfolio_value=1000.0,
        lot_size=1,
        order_type="MKT",
    )
    mapped = _by_symbol_side(orders)
    assert ("AAA", "SELL") in mapped
    assert mapped[("AAA", "SELL")]["quantity"] == 1


def test_build_rebalance_orders_applies_min_notional_deadband_when_configured():
    # target_qty = 2, current = 3, tradable delta = -1 (order notional = 50)
    # deadband_min_notional=60 should skip this SELL.
    orders = build_rebalance_orders(
        target_weights={"AAA": 0.1},
        current_positions={"AAA": 3.0},
        price_map={"AAA": 50.0},
        portfolio_value=1000.0,
        lot_size=1,
        deadband_min_notional=60.0,
        order_type="MKT",
    )
    assert orders == []


def test_build_rebalance_orders_applies_min_weight_deadband_when_configured():
    # target_qty = 2, current = 3, tradable delta = -1 (order weight = 50 / 1000 = 0.05)
    # deadband_min_weight=0.06 should skip this SELL.
    orders = build_rebalance_orders(
        target_weights={"AAA": 0.1},
        current_positions={"AAA": 3.0},
        price_map={"AAA": 50.0},
        portfolio_value=1000.0,
        lot_size=1,
        deadband_min_weight=0.06,
        order_type="MKT",
    )
    assert orders == []
