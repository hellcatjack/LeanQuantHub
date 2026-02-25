from pathlib import Path
import csv
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, Project, TradeOrder, TradeRun
from app.services.trade_riskoff_validation import validate_trade_run_riskoff_alignment


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _write_items(path: Path, symbols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        for idx, symbol in enumerate(symbols, start=1):
            writer.writerow({"symbol": symbol, "weight": "1.0", "score": "1.0", "rank": str(idx)})


def test_validate_trade_run_riskoff_alignment_pass(tmp_path):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path, ["VGSH"])
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
            summary={
                "risk_off": True,
                "risk_off_mode": "defensive",
                "risk_off_symbol": "VGSH",
                "algorithm_parameters": {"risk_off_symbols": "VGSH,IEF,GLD,TLT"},
            },
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(project_id=project.id, decision_snapshot_id=snapshot.id, status="done", mode="paper", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add(
            TradeOrder(
                run_id=run.id,
                client_order_id="o1",
                symbol="SPY",
                side="SELL",
                quantity=10,
                status="FILLED",
            )
        )
        session.add(
            TradeOrder(
                run_id=run.id,
                client_order_id="o2",
                symbol="VGSH",
                side="BUY",
                quantity=10,
                status="FILLED",
            )
        )
        session.commit()

        result = validate_trade_run_riskoff_alignment(session, run_id=run.id)
        assert result["status"] == "pass"
        assert result["message"] == "risk_off_trade_alignment_ok"
    finally:
        session.close()


def test_validate_trade_run_riskoff_alignment_failed_on_unexpected_buy(tmp_path):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path, ["VGSH"])
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
            summary={
                "risk_off": 1,
                "risk_off_mode": "defensive",
                "risk_off_symbol": "VGSH",
                "algorithm_parameters": {"risk_off_symbols": "VGSH,IEF,GLD,TLT"},
            },
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(project_id=project.id, decision_snapshot_id=snapshot.id, status="done", mode="paper", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add(
            TradeOrder(
                run_id=run.id,
                client_order_id="o3",
                symbol="SPY",
                side="BUY",
                quantity=5,
                status="FILLED",
            )
        )
        session.commit()

        result = validate_trade_run_riskoff_alignment(session, run_id=run.id)
        assert result["status"] == "failed"
        assert "unexpected_buy_symbols" in (result.get("violations") or [])
    finally:
        session.close()


def test_validate_trade_run_riskoff_alignment_skipped_when_risk_off_false(tmp_path):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path, ["AAPL"])
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
            summary={"risk_off": False, "risk_off_mode": "cash"},
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(project_id=project.id, decision_snapshot_id=snapshot.id, status="done", mode="paper", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        result = validate_trade_run_riskoff_alignment(session, run_id=run.id)
        assert result["status"] == "skipped"
        assert result["message"] == "risk_off_not_triggered"
    finally:
        session.close()


def test_validate_trade_run_riskoff_alignment_risk_off_only_picks_latest_risk_off_run(tmp_path):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path_on = tmp_path / "risk_on_items.csv"
        _write_items(items_path_on, ["AAPL"])
        snapshot_on = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path_on),
            summary={"risk_off": False},
        )
        session.add(snapshot_on)
        session.commit()
        session.refresh(snapshot_on)

        items_path_off = tmp_path / "risk_off_items.csv"
        _write_items(items_path_off, ["VGSH"])
        snapshot_off = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path_off),
            summary={
                "risk_off": True,
                "risk_off_mode": "defensive",
                "risk_off_symbol": "VGSH",
                "algorithm_parameters": {"risk_off_symbols": "VGSH,IEF,GLD,TLT"},
            },
        )
        session.add(snapshot_off)
        session.commit()
        session.refresh(snapshot_off)

        run_off = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot_off.id,
            status="done",
            mode="paper",
            params={},
        )
        session.add(run_off)
        session.commit()
        session.refresh(run_off)

        session.add(
            TradeOrder(
                run_id=run_off.id,
                client_order_id="riskoff-buy",
                symbol="VGSH",
                side="BUY",
                quantity=5,
                status="FILLED",
            )
        )
        session.commit()

        run_on = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot_on.id,
            status="done",
            mode="paper",
            params={},
        )
        session.add(run_on)
        session.commit()
        session.refresh(run_on)

        result = validate_trade_run_riskoff_alignment(
            session,
            project_id=project.id,
            risk_off_only=True,
        )
        assert result["status"] == "pass"
        assert result["run_id"] == run_off.id
    finally:
        session.close()


def test_validate_trade_run_riskoff_alignment_risk_off_only_returns_skipped_when_missing(tmp_path):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "risk_on_items.csv"
        _write_items(items_path, ["AAPL"])
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
            summary={"risk_off": False},
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            status="done",
            mode="paper",
            params={},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = validate_trade_run_riskoff_alignment(
            session,
            project_id=project.id,
            risk_off_only=True,
        )
        assert result["status"] == "skipped"
        assert result["message"] == "risk_off_trade_run_not_found"
    finally:
        session.close()
