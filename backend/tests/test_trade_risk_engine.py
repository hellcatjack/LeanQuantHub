from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_risk_engine import evaluate_orders


def test_risk_blocks_large_order():
    orders = [
        {"symbol": "AAA", "side": "BUY", "quantity": 100, "price": 100.0},
    ]
    ok, blocked, reasons = evaluate_orders(
        orders,
        max_order_notional=5000,
        max_position_ratio=None,
        portfolio_value=10000,
    )
    assert ok is False
    assert blocked and blocked[0]["symbol"] == "AAA"
    assert "max_order_notional" in reasons[0]
