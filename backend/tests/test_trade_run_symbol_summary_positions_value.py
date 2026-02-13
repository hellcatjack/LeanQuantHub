from __future__ import annotations

from pathlib import Path
import csv
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, Project, TradeRun
import app.services.trade_run_summary as trade_run_summary


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def _write_items(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        writer.writerow({"symbol": "AAA", "weight": "0.2", "score": "1.0", "rank": "1"})


def test_build_symbol_summary_prefers_positions_market_value_and_includes_non_targets(tmp_path, monkeypatch):
    Session = _make_session_factory()
    session = Session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path)
        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path=str(items_path))
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            status="queued",
            mode="paper",
            params={"portfolio_value": 5000.0},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        monkeypatch.setattr(
            trade_run_summary,
            "read_positions",
            lambda _root: {
                "items": [
                    {"symbol": "AAA", "quantity": 10.0, "market_value": 900.0},
                    {"symbol": "ZZZ", "quantity": 5.0, "market_value": 500.0},
                ],
                "stale": False,
                "source_detail": "ib_holdings",
            },
            raising=False,
        )
        # Force price map to empty so the summary must rely on positions-provided market values.
        monkeypatch.setattr(trade_run_summary, "_build_price_map", lambda _symbols: {}, raising=False)

        items = trade_run_summary.build_symbol_summary(session, run.id)
        by_symbol = {item["symbol"]: item for item in items}

        assert set(by_symbol.keys()) == {"AAA", "ZZZ"}

        assert by_symbol["AAA"]["current_value"] == 900.0
        assert by_symbol["ZZZ"]["current_value"] == 500.0

        assert by_symbol["ZZZ"]["target_weight"] == 0.0
        assert by_symbol["ZZZ"]["target_value"] == 0.0
        assert by_symbol["ZZZ"]["delta_value"] == -500.0

        assert abs(by_symbol["AAA"]["current_weight"] - (900.0 / 5000.0)) <= 1e-9
        assert abs(by_symbol["AAA"]["delta_weight"] - (0.2 - 900.0 / 5000.0)) <= 1e-9
        assert abs(by_symbol["ZZZ"]["current_weight"] - (500.0 / 5000.0)) <= 1e-9
        assert abs(by_symbol["ZZZ"]["delta_weight"] - (0.0 - 500.0 / 5000.0)) <= 1e-9
    finally:
        session.close()


def test_build_symbol_summary_falls_back_to_quotes_when_positions_market_value_zero(tmp_path, monkeypatch):
    Session = _make_session_factory()
    session = Session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=None,
            status="queued",
            mode="paper",
            params={"portfolio_value": 5000.0},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        monkeypatch.setattr(
            trade_run_summary,
            "read_positions",
            lambda _root: {
                "items": [
                    {"symbol": "AMD", "quantity": 2.0, "market_value": 0.0},
                ],
                "stale": False,
                "source_detail": "ib_holdings",
            },
            raising=False,
        )
        monkeypatch.setattr(
            trade_run_summary,
            "_build_price_map",
            lambda _symbols: {"AMD": 100.0},
            raising=False,
        )

        items = trade_run_summary.build_symbol_summary(session, run.id)
        by_symbol = {item["symbol"]: item for item in items}

        assert set(by_symbol.keys()) == {"AMD"}
        assert by_symbol["AMD"]["current_value"] == 200.0
        assert by_symbol["AMD"]["target_weight"] == 0.0
        assert by_symbol["AMD"]["target_value"] == 0.0
        assert by_symbol["AMD"]["delta_value"] == -200.0
        assert abs(by_symbol["AMD"]["current_weight"] - (200.0 / 5000.0)) <= 1e-9
        assert abs(by_symbol["AMD"]["delta_weight"] - (0.0 - 200.0 / 5000.0)) <= 1e-9
    finally:
        session.close()
