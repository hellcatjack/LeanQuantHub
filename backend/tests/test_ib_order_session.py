from app.services.ib_market import IBRequestSession


class Dummy:
    pass


def test_ib_request_session_order_events_collect():
    session = IBRequestSession("127.0.0.1", 7497, 1, timeout=0.1)

    session.orderStatus(1, "Submitted", 0, 10, 0.0, 0, 0, 0.0, "", 0.0, 0.0)

    exec_payload = Dummy()
    exec_payload.orderId = 1
    exec_payload.shares = 10
    exec_payload.price = 100.0
    exec_payload.time = "20260122 09:31:00"
    exec_payload.execId = "E1"
    session.execDetails(1, None, exec_payload)

    commission = Dummy()
    commission.execId = "E1"
    commission.commission = 1.5
    session.commissionReport(commission)

    payload = session._order_events.get(1)
    assert payload["status"] == "Submitted"
    assert payload["fills"][0]["quantity"] == 10
    assert payload["fills"][0]["price"] == 100.0
    assert payload["commission"] == 1.5
