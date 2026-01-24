from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from types import SimpleNamespace

from app.models import Base, TradeOrder, TradeRun
import app.services.trade_executor as trade_executor


def test_trade_run_records_portfolio_value(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "probe_ib_connection", lambda _session: SimpleNamespace(status="connected"))
    monkeypatch.setattr(trade_executor, "ensure_ib_client_id", lambda _s: SimpleNamespace())
    monkeypatch.setattr(trade_executor, "resolve_ib_api_mode", lambda _s: "mock")
    monkeypatch.setattr(
        trade_executor,
        "fetch_market_snapshots",
        lambda *a, **k: [{"symbol": "SPY", "data": {"last": 100}}],
    )
    monkeypatch.setattr(trade_executor, "evaluate_orders", lambda *_a, **_k: (True, [], []))
    monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda *_a, **_k: {"NetLiquidation": 100000})

    session = Session()
    try:
        run = TradeRun(project_id=1, decision_snapshot_id=1, mode="paper", status="queued", params={})
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
    finally:
        session.close()

    trade_executor.execute_trade_run(run.id, dry_run=True)

    session = Session()
    try:
        refreshed = session.get(TradeRun, run.id)
        assert refreshed.params.get("portfolio_value") == 100000
    finally:
        session.close()
