from pathlib import Path
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services import lean_execution
from app.services.trade_orders import create_trade_order


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_apply_execution_events_updates_order(monkeypatch):
    engine = _make_engine()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    try:
        payload = {
            "client_order_id": "oi_0_0_123",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 1,
            "order_type": "MKT",
        }
        result = create_trade_order(session, payload)
        session.commit()

        monkeypatch.setattr(lean_execution, "SessionLocal", Session, raising=False)

        events = [
            {
                "tag": "oi_0_0_123",
                "status": "Submitted",
                "order_id": 1001,
                "time": "2026-01-28T00:00:00Z",
            },
            {
                "tag": "oi_0_0_123",
                "status": "Filled",
                "filled": 1,
                "fill_price": 100.0,
                "time": "2026-01-28T00:00:01Z",
            },
        ]
        lean_execution.apply_execution_events(events)

        verify_session = Session()
        try:
            refreshed = (
                verify_session.query(type(result.order))
                .filter_by(client_order_id="oi_0_0_123")
                .one()
            )
            assert refreshed.status == "FILLED"
            assert refreshed.filled_quantity == 1
            assert refreshed.avg_fill_price == 100.0
            assert refreshed.ib_order_id == 1001
        finally:
            verify_session.close()
    finally:
        session.close()
