from pathlib import Path
import sys
import csv
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeRun, DecisionSnapshot, TradeOrder, TradeSettings
import app.services.trade_executor as trade_executor
from app.services.trade_order_builder import build_orders


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def _write_items(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        writer.writerow({"symbol": "AAA", "weight": "0.2", "score": "1.0", "rank": "1"})
        writer.writerow({"symbol": "BBB", "weight": "0.1", "score": "0.9", "rank": "2"})


def test_execute_builds_orders_from_snapshot(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(
        trade_executor,
        "probe_ib_connection",
        lambda _session: SimpleNamespace(status="connected"),
    )
    monkeypatch.setattr(
        trade_executor,
        "fetch_market_snapshots",
        lambda *a, **k: [
            {"symbol": "AAA", "data": {"last": 50}},
            {"symbol": "BBB", "data": {"last": 25}},
        ],
    )
    session = Session()
    try:
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
        assert result.status in {"done", "running", "blocked", "failed", "queued"}
        orders = session.query(TradeOrder).filter_by(run_id=run.id).all()
        assert len(orders) == 2
    finally:
        session.close()


def test_merge_risk_params_override():
    defaults = {"max_order_notional": 1000, "max_symbols": 5}
    overrides = {"max_order_notional": 500}
    merged = trade_executor._merge_risk_params(defaults, overrides)
    assert merged["max_order_notional"] == 500
    assert merged["max_symbols"] == 5


def test_execute_blocks_when_execution_source_not_ib(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(
        trade_executor,
        "fetch_market_snapshots",
        lambda *a, **k: [{"symbol": "AAA", "data": {"last": 50}}],
    )
    session = Session()
    try:
        settings = TradeSettings(risk_defaults={}, execution_data_source="alpha")
        session.add(settings)
        session.commit()

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
        assert result.message == "execution_data_source_mismatch"
    finally:
        session.close()


def test_build_orders_rounding():
    items = [{"symbol": "SPY", "weight": 0.1}]
    price_map = {"SPY": 60}
    orders = build_orders(items, price_map=price_map, portfolio_value=1000)
    assert orders[0]["quantity"] == 2
