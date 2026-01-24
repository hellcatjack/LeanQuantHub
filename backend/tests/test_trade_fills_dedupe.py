from pathlib import Path
import sys
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeFill, TradeOrder
from app.services import ib_orders


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_apply_fill_dedupes_exec_id():
    session = _make_session()
    try:
        order = TradeOrder(
            client_order_id="c1",
            symbol="SPY",
            side="BUY",
            quantity=1,
            order_type="MKT",
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        ib_orders.apply_fill_to_order(
            session,
            order,
            fill_qty=1,
            fill_price=10,
            fill_time=datetime.utcnow(),
            exec_id="E1",
        )
        ib_orders.apply_fill_to_order(
            session,
            order,
            fill_qty=1,
            fill_price=10,
            fill_time=datetime.utcnow(),
            exec_id="E1",
        )
        session.refresh(order)
        fills = (
            session.query(TradeFill)
            .filter(TradeFill.order_id == order.id)
            .all()
        )
        assert len(fills) == 1
        assert order.filled_quantity == 1
    finally:
        session.close()
