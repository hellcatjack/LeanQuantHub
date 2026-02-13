from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_order_builder import build_orders


def test_build_orders_requires_limit_price_for_lmt():
    orders = build_orders(
        [{"symbol": "SPY", "weight": 0.1}],
        price_map={"SPY": 100},
        portfolio_value=100000,
        order_type="LMT",
        limit_price=None,
    )
    assert orders == []


def test_build_orders_allows_adaptive_lmt_without_limit_price():
    orders = build_orders(
        [{"symbol": "SPY", "weight": 0.1}],
        price_map={"SPY": 100},
        portfolio_value=100000,
        order_type="ADAPTIVE_LMT",
        limit_price=None,
    )
    assert len(orders) == 1
    assert orders[0]["order_type"] == "ADAPTIVE_LMT"
    assert orders[0]["limit_price"] is None
