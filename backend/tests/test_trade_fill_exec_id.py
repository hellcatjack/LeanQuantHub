from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, TradeOrder
from app.services.ib_orders import apply_fill_to_order


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_apply_fill_to_order_generates_exec_id():
    Session = _make_session_factory()
    session = Session()
    order = TradeOrder(
        run_id=None,
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=1,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    fill = apply_fill_to_order(
        session,
        order,
        fill_qty=1,
        fill_price=100,
        fill_time=datetime.utcnow(),
    )
    assert fill.exec_id
