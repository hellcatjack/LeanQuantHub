from app.services.trade_direct_order import validate_direct_order_payload


def test_validate_direct_order_accepts_lmt_without_limit_price():
    payload = {
        "mode": "paper",
        "order_type": "LMT",
        "side": "BUY",
        "quantity": 1,
        "symbol": "AAPL",
    }
    assert validate_direct_order_payload(payload) == (True, "")


def test_validate_direct_order_rejects_lmt_invalid_limit_price():
    payload = {
        "mode": "paper",
        "order_type": "LMT",
        "side": "BUY",
        "quantity": 1,
        "symbol": "AAPL",
        "limit_price": -1,
    }
    assert validate_direct_order_payload(payload) == (False, "limit_price_invalid")


def test_validate_direct_order_accepts_adaptive_lmt_without_limit_price():
    payload = {
        "mode": "paper",
        "order_type": "ADAPTIVE_LMT",
        "side": "BUY",
        "quantity": 1,
        "symbol": "AAPL",
    }
    assert validate_direct_order_payload(payload) == (True, "")


def test_validate_direct_order_accepts_peg_mid_without_limit_price():
    payload = {
        "mode": "paper",
        "order_type": "PEG MID",
        "side": "BUY",
        "quantity": 1,
        "symbol": "AAPL",
    }
    assert validate_direct_order_payload(payload) == (True, "")
