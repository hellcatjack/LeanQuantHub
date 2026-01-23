from app.models import TradeFill


def test_trade_fill_fields_exist():
    fill = TradeFill(
        order_id=1,
        exec_id="E1",
        filled_qty=10,
        price=100,
        commission=1.2,
    )
    assert fill.exec_id == "E1"
