from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services.trade_orders import create_trade_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_client_order_id_idempotent_without_commit():
    session = _make_session()
    try:
        payload = {
            "client_order_id": "run-1-SPY",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 10,
            "order_type": "MKT",
        }
        first = create_trade_order(session, payload)
        second = create_trade_order(session, payload)
        assert first.order is second.order
        assert second.created is False
    finally:
        session.close()
