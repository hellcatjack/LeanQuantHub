from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.trade_cash_guard import apply_cash_budget_to_order_drafts


def test_cash_guard_shrinks_buy_without_using_unfilled_sell_proceeds():
    orders = [
        {"symbol": "ZZZ", "side": "SELL", "quantity": 10.0, "order_type": "MKT"},
        {"symbol": "AAA", "side": "BUY", "quantity": 20.0, "order_type": "MKT"},
    ]

    adjusted, meta = apply_cash_budget_to_order_drafts(
        orders,
        price_map={"AAA": 100.0, "ZZZ": 100.0},
        cash_available=950.0,
        portfolio_value=10_000.0,
        cash_buffer_ratio=0.0,
        lot_size=1,
        min_qty=1,
        fee_bps=0.0,
        price_buffer_bps=0.0,
    )

    assert [(item["symbol"], item["side"], item["quantity"]) for item in adjusted] == [
        ("ZZZ", "SELL", 10.0),
        ("AAA", "BUY", 9.0),
    ]
    assert meta["applied"] is True
    assert meta["estimated_buy_cost_before"] == 2000.0
    assert meta["estimated_buy_cost_after"] == 900.0
    assert meta["adjustments"] == [
        {
            "symbol": "AAA",
            "side": "BUY",
            "action": "reduced",
            "requested_quantity": 20.0,
            "approved_quantity": 9.0,
            "estimated_price": 100.0,
            "estimated_cost_before": 2000.0,
            "estimated_cost_after": 900.0,
        }
    ]


def test_cash_guard_skips_buy_when_affordable_quantity_is_below_lot_size():
    adjusted, meta = apply_cash_budget_to_order_drafts(
        [{"symbol": "AAA", "side": "BUY", "quantity": 30.0, "order_type": "MKT"}],
        price_map={"AAA": 100.0},
        cash_available=250.0,
        portfolio_value=10_000.0,
        cash_buffer_ratio=0.0,
        lot_size=10,
        min_qty=10,
        fee_bps=0.0,
        price_buffer_bps=0.0,
    )

    assert adjusted == []
    assert meta["blocked_no_orders"] is True
    assert meta["adjustments"][0]["action"] == "skipped"
    assert meta["adjustments"][0]["approved_quantity"] == 0.0
