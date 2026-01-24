from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.models import Base, DecisionSnapshot, TradeOrder, TradeRun
import app.services.trade_executor as trade_executor


def test_trade_run_records_portfolio_value(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "SPY", "last": 100}], "stale": False},
        raising=False,
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


def test_trade_run_uses_account_summary_for_portfolio_value_when_no_orders(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 100}], "stale": False},
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "evaluate_orders", lambda *_a, **_k: (True, [], []))
    monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda *_a, **_k: {"NetLiquidation": 50000})
    monkeypatch.setattr(
        trade_executor,
        "_read_decision_items",
        lambda *_a, **_k: [{"symbol": "AAA", "weight": 0.1}],
    )

    session = Session()
    try:
        snapshot = DecisionSnapshot(
            project_id=1,
            status="done",
            snapshot_date="2026-01-16",
            items_path="dummy.json",
        )
        session.add(snapshot)
        session.commit()
        run = TradeRun(project_id=1, decision_snapshot_id=snapshot.id, mode="paper", status="queued", params={})
        session.add(run)
        session.commit()
    finally:
        session.close()

    trade_executor.execute_trade_run(run.id, dry_run=True)

    session = Session()
    try:
        refreshed = session.get(TradeRun, run.id)
        assert refreshed.message != "portfolio_value_required"
        assert refreshed.params.get("portfolio_value") == 50000
    finally:
        session.close()
