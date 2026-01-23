from app.services.trade_executor import _apply_order_status


def test_apply_order_status_updates_fields():
    order = {"status": "NEW"}
    _apply_order_status(order, status="Submitted")
    assert order["status"] == "SUBMITTED"
