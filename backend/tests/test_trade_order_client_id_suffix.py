from app.services.trade_orders import build_manual_client_order_id


def test_build_manual_client_order_id_appends_suffix():
    assert build_manual_client_order_id("manual-abc", 35) == "manual-abc-z"
