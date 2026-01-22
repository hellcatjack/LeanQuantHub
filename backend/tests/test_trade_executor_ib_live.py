from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
import app.services.trade_executor as trade_executor


def test_trade_executor_prefers_live_orders(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    monkeypatch.setattr(
        "app.services.ib_orders.submit_orders_live",
        lambda *a, **k: {"status": "filled", "orders": []},
    )

    result = trade_executor._submit_ib_orders(session, [], price_map={})
    assert result["status"] == "filled"
    session.close()
