from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder
from app.services.ib_orders import apply_fill_to_order


def test_apply_fill_updates_partial_and_avg_price():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    order = TradeOrder(
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=10,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    apply_fill_to_order(session, order, fill_qty=4, fill_price=100.0, fill_time=datetime.utcnow())
    session.refresh(order)
    assert order.status == "PARTIAL"
    assert order.filled_quantity == 4
    assert order.avg_fill_price == 100.0

    apply_fill_to_order(session, order, fill_qty=6, fill_price=110.0, fill_time=datetime.utcnow())
    session.refresh(order)
    assert order.status == "FILLED"
    assert order.filled_quantity == 10
    assert round(order.avg_fill_price, 6) == 106.0

    session.close()
