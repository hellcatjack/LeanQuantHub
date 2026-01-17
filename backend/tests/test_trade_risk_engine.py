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
        max_total_notional=None,
        max_symbols=None,
        cash_available=None,
        min_cash_buffer_ratio=None,
    )
    assert ok is False
    assert blocked and blocked[0]["symbol"] == "AAA"
    assert "max_order_notional" in reasons[0]


def test_risk_max_total_notional_blocks():
    ok, blocked, reasons = evaluate_orders(
        [
            {"symbol": "A", "quantity": 10, "price": 10},
            {"symbol": "B", "quantity": 10, "price": 10},
        ],
        max_order_notional=None,
        max_position_ratio=None,
        portfolio_value=1000,
        max_total_notional=150,
        max_symbols=None,
        cash_available=None,
        min_cash_buffer_ratio=None,
    )
    assert ok is False
    assert any(r.startswith("max_total_notional") for r in reasons)


def test_risk_max_symbols_blocks():
    ok, blocked, reasons = evaluate_orders(
        [
            {"symbol": "A", "quantity": 1, "price": 10},
            {"symbol": "B", "quantity": 1, "price": 10},
        ],
        max_order_notional=None,
        max_position_ratio=None,
        portfolio_value=1000,
        max_total_notional=None,
        max_symbols=1,
        cash_available=None,
        min_cash_buffer_ratio=None,
    )
    assert ok is False
    assert any(r.startswith("max_symbols") for r in reasons)


def test_risk_min_cash_buffer_ratio_blocks():
    ok, blocked, reasons = evaluate_orders(
        [{"symbol": "A", "quantity": 50, "price": 10}],
        max_order_notional=None,
        max_position_ratio=None,
        portfolio_value=1000,
        max_total_notional=None,
        max_symbols=None,
        cash_available=100,
        min_cash_buffer_ratio=0.2,
    )
    assert ok is False
    assert any(r.startswith("min_cash_buffer_ratio") for r in reasons)
