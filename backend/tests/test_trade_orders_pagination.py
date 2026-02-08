from contextlib import contextmanager
from pathlib import Path
import sys

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.routes import trade as trade_routes
from app.services.trade_orders import create_trade_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_orders_total_count_header():
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    trade_routes.get_session = _get_session  # type: ignore[attr-defined]

    create_trade_order(
        session,
        {
            "client_order_id": "manual-1",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()

    response = Response()
    result = trade_routes.list_trade_orders(limit=1, offset=0, run_id=None, response=response)
    assert response.headers.get("X-Total-Count") == "1"
    assert len(result) == 1

    session.close()


def test_orders_sorted_by_id_desc():
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    trade_routes.get_session = _get_session  # type: ignore[attr-defined]

    create_trade_order(
        session,
        {
            "client_order_id": "manual-1",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    create_trade_order(
        session,
        {
            "client_order_id": "manual-2",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        },
    )
    session.commit()

    response = Response()
    result = trade_routes.list_trade_orders(limit=20, offset=0, run_id=None, response=response)
    ids = [item.id for item in result]
    assert ids == sorted(ids, reverse=True)

    session.close()
