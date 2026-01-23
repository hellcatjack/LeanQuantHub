from app.services.ib_execution import ExecutionEventBuffer


def test_execution_event_buffer_records_updates():
    buf = ExecutionEventBuffer()
    buf.on_order_status(order_id=1, status="Submitted")
    buf.on_execution(exec_id="E1", order_id=1, qty=10, price=100.0)
    assert buf.order_statuses[1] == "Submitted"
    assert buf.executions["E1"]["qty"] == 10
