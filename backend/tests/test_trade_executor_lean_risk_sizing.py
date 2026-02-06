from pathlib import Path
import sys
import csv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeRun, DecisionSnapshot, TradeOrder, TradeSettings
import app.services.trade_executor as trade_executor


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _write_items(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        writer.writerow({"symbol": "AAA", "weight": "0.2", "score": "1.0", "rank": "1"})


def test_lean_mode_sizes_intent_orders_before_risk_gate(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 50}], "stale": False},
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "fetch_account_summary",
        lambda *_a, **_k: {"NetLiquidation": 10000, "cash_available": 10000},
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "launch_execution", lambda **_kwargs: None, raising=False)

    session = Session()
    try:
        settings = TradeSettings(risk_defaults={"max_order_notional": 1000}, execution_data_source="lean")
        session.add(settings)

        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path)
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            status="queued",
            mode="paper",
            params={"portfolio_value": 10000},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True)
        assert result.status == "blocked"
        assert result.message == "max_order_notional:AAA"

        orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        assert len(orders) == 1
        assert float(orders[0].quantity) == 40.0
    finally:
        session.close()

