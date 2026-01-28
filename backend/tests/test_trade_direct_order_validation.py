from app.services.trade_direct_order import validate_direct_order_payload


def test_validate_direct_order_rejects_lmt():
    payload = {
        "mode": "paper",
        "order_type": "LMT",
        "side": "BUY",
        "quantity": 1,
        "symbol": "AAPL",
    }
    assert validate_direct_order_payload(payload) == (False, "order_type_invalid")
