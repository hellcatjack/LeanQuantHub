from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from types import SimpleNamespace

from app.models import Base, TradeOrder, TradeRun, TradeSettings
import app.services.trade_executor as trade_executor
from app.services.ib_execution import ExecutionEvent


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


def test_execute_trade_run_sets_partial_status(monkeypatch):
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

    def _fake_submit(session_arg, orders, price_map=None):
        return {"filled": 1, "rejected": 1}

    monkeypatch.setattr(trade_executor, "_submit_ib_orders", _fake_submit)
    trade_executor._finalize_run_status(session, run, filled=1, rejected=1, cancelled=0)
    session.refresh(run)
    assert run.status == "partial"
    session.close()


def test_resolve_snapshot_price_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(
        trade_executor,
        "_read_local_snapshot",
        lambda symbol: {"last": 10.0},
    )
    assert trade_executor._resolve_snapshot_price("SPY", {}) == 10.0


def test_execute_trade_run_updates_ib_status(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(
        trade_executor,
        "probe_ib_connection",
        lambda _session: SimpleNamespace(status="connected"),
    )
    monkeypatch.setattr(trade_executor, "ensure_ib_client_id", lambda _s: SimpleNamespace())
    monkeypatch.setattr(trade_executor, "resolve_ib_api_mode", lambda _s: "ib")
    monkeypatch.setattr(
        trade_executor,
        "fetch_market_snapshots",
        lambda *a, **k: [{"symbol": "SPY", "data": {"last": 100}}],
    )
    monkeypatch.setattr(trade_executor, "evaluate_orders", lambda *_a, **_k: (True, [], []))
    monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda *_a, **_k: {"cash_available": 10000})

    def _fake_submit(session_arg, orders, price_map=None):
        return {
            "filled": 0,
            "rejected": 0,
            "cancelled": 0,
            "events": [
                ExecutionEvent(
                    order_id=orders[0].id,
                    status="SUBMITTED",
                    exec_id=None,
                    filled=0,
                    avg_price=None,
                    ib_order_id=123,
                )
            ],
        }

    monkeypatch.setattr(trade_executor, "_submit_ib_orders", _fake_submit)

    session = Session()
    order_id = None
    try:
        settings = TradeSettings(risk_defaults={}, execution_data_source="ib")
        session.add(settings)
        session.commit()
        run = TradeRun(project_id=1, decision_snapshot_id=1, mode="paper", status="queued", params={"portfolio_value": 1000})
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
        order_id = order.id
    finally:
        session.close()

    result = trade_executor.execute_trade_run(run.id, dry_run=False)
    assert result.status == "running"
    session = Session()
    try:
        updated = session.get(TradeOrder, order_id)
        assert updated.status == "SUBMITTED"
        assert updated.ib_order_id == 123
    finally:
        session.close()
