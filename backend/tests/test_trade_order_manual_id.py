from app.services.trade_orders import apply_manual_client_order_id


def test_apply_manual_client_order_id_suffixes_and_preserves_original():
    payload = {"client_order_id": "manual-test", "params": {"source": "direct"}}
    updated = apply_manual_client_order_id(payload, seq_id=123)
    assert updated["client_order_id"].startswith("manual-test-")
    assert updated["params"]["original_client_order_id"] == "manual-test"
