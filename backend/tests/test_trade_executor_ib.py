from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TradeOrder, TradeRun
import app.services.trade_executor as trade_executor


def test_execute_trade_run_uses_ib_submit(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    run = TradeRun(project_id=1, mode="paper", status="queued", params={"portfolio_value": 1000})
    session.add(run)
    session.commit()
    order = TradeOrder(
        run_id=run.id,
        client_order_id="run-1-SPY-BUY",
        symbol="SPY",
        side="BUY",
        quantity=1,
        order_type="MKT",
        status="NEW",
    )
    session.add(order)
    session.commit()

    called = {"ok": False}

    def _fake_submit(session_arg, orders, price_map=None):
        called["ok"] = True
        return {"filled": 1, "rejected": 0}

    monkeypatch.setattr(trade_executor, "_submit_ib_orders", _fake_submit)
    trade_executor._execute_orders_with_ib(session, run, [order], price_map={"SPY": 100.0})
    assert called["ok"] is True
    session.close()
