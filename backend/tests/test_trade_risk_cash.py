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

from app.models import Base, Project, TradeRun, DecisionSnapshot
import app.services.trade_executor as trade_executor


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


def test_trade_executor_injects_cash_available(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(
        trade_executor,
        "fetch_market_snapshots",
        lambda *a, **k: [{"symbol": "AAA", "data": {"last": 50}}],
    )
    monkeypatch.setattr(
        trade_executor,
        "probe_ib_connection",
        lambda _s: SimpleNamespace(status="connected"),
    )
    monkeypatch.setattr(
        trade_executor,
        "fetch_account_summary",
        lambda *_a, **_k: {"cash_available": 1234},
    )
    captured = {"cash": None}

    def _evaluate_orders(orders, **kwargs):
        captured["cash"] = kwargs.get("cash_available")
        return True, [], []

    monkeypatch.setattr(trade_executor, "evaluate_orders", _evaluate_orders)

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

        trade_executor.execute_trade_run(run.id, dry_run=True)
        assert captured["cash"] == 1234
    finally:
        session.close()
