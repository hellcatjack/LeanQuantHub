from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from types import SimpleNamespace

from app.models import Base, DecisionSnapshot, TradeRun
import app.services.trade_executor as trade_executor


def test_trade_run_sets_order_intent_path(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAPL", "last": 100.0}], "stale": False},
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "evaluate_orders", lambda *_a, **_k: (True, [], []))
    monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda *_a, **_k: {"NetLiquidation": 100000})
    monkeypatch.setattr(trade_executor, "_read_decision_items", lambda *_a, **_k: [{"symbol": "AAPL", "weight": 0.1}])
    monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

    session = Session()
    try:
        snapshot = DecisionSnapshot(
            project_id=1,
            status="success",
            snapshot_date="2026-01-16",
            items_path="dummy.csv",
        )
        session.add(snapshot)
        session.commit()
        run = TradeRun(project_id=1, decision_snapshot_id=snapshot.id, mode="paper", status="queued", params={})
        session.add(run)
        session.commit()
        run_id = run.id
    finally:
        session.close()

    trade_executor.execute_trade_run(run_id, dry_run=True)

    session = Session()
    try:
        refreshed = session.get(TradeRun, run_id)
        assert "order_intent_path" in (refreshed.params or {})
    finally:
        session.close()
