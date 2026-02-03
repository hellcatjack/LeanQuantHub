from datetime import datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeOrder, TradeSettings
from app.services import trade_order_recovery


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_recovery_cancels_and_replaces_new_order(monkeypatch):
    session = _make_session()
    try:
        session.add(
            TradeSettings(
                risk_defaults={},
                execution_data_source="ib",
                auto_recovery={"new_timeout_seconds": 1, "max_auto_retries": 1},
            )
        )
        session.commit()
        order = TradeOrder(
            client_order_id="c1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="MKT",
            status="NEW",
            filled_quantity=0.0,
            created_at=datetime.utcnow() - timedelta(seconds=10),
        )
        session.add(order)
        session.commit()

        monkeypatch.setattr(trade_order_recovery, "_probe_ib_socket", lambda *args, **kwargs: True, raising=False)
        result = trade_order_recovery.run_auto_recovery(session, now=datetime.utcnow())

        assert result["cancelled"] == 1
        assert result["replaced"] == 1
    finally:
        session.close()
