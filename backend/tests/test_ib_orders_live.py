from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeFill, TradeOrder
from app.services.ib_orders import submit_orders_live


def test_submit_orders_live_maps_fills(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    order = TradeOrder(
        client_order_id="run-1-AAPL",
        symbol="AAPL",
        side="BUY",
        quantity=10,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    class FakeAdapter:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def place_order(self, *args, **kwargs):
            return {
                "order_id": 99,
                "status": "Filled",
                "filled": 10,
                "avg_fill_price": 100.0,
                "fills": [{"quantity": 10, "price": 100.0, "time": "20260122 09:31:00"}],
                "commission": 1.0,
            }, None

    monkeypatch.setattr("app.services.ib_orders.ib_adapter", lambda *a, **k: FakeAdapter())

    result = submit_orders_live(session, [order], price_map={"AAPL": 100.0})
    assert result["status"] == "filled"
    row = session.get(TradeOrder, order.id)
    assert row.status == "FILLED"
    assert row.filled_quantity == 10
    assert row.avg_fill_price == 100.0
    assert session.query(TradeFill).count() == 1
    session.close()
