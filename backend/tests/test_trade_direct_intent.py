from app.services.trade_direct_intent import build_direct_intent_items


def test_build_direct_intent_sell_negative():
    items = build_direct_intent_items(order_id=10, symbol="AAPL", side="SELL", quantity=2)
    assert items == [
        {
            "order_intent_id": "direct:10",
            "symbol": "AAPL",
            "quantity": -2.0,
            "order_type": "MKT",
            "limit_price": None,
        }
    ]


def test_build_direct_intent_buy_positive():
    items = build_direct_intent_items(order_id=11, symbol="NVDA", side="BUY", quantity=1)
    assert items == [
        {
            "order_intent_id": "direct:11",
            "symbol": "NVDA",
            "quantity": 1.0,
            "order_type": "MKT",
            "limit_price": None,
        }
    ]
