from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder
from app.services.ib_orders import submit_orders_mock


def test_submit_orders_mock_fills_all():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    order = TradeOrder(
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=2,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    result = submit_orders_mock(session, [order], price_map={"SPY": 123.0})
    session.refresh(order)
    assert result["filled"] == 1
    assert order.status == "FILLED"
    assert order.avg_fill_price == 123.0
    session.close()
