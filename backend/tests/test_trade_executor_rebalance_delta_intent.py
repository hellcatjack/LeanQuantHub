from __future__ import annotations

from pathlib import Path
import csv
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, Project, TradeOrder, TradeRun, TradeSettings
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


def _write_items(path: Path, *, symbol: str, weight: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        writer.writerow({"symbol": symbol, "weight": str(weight), "score": "1.0", "rank": "1"})


def test_execute_trade_run_builds_delta_intent_using_latest_net_liq(tmp_path, monkeypatch):
    """Auto trade run must size targets from latest NetLiquidation and positions.json.

    Requirements covered:
    - positions.json current holdings include non-target symbols
    - target_qty computed from snapshot weights + latest price/net value
    - delta orders -> intent quantity mode (SELL negative) with sell-first ordering
    """

    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 100.0}], "stale": False},
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "read_positions",
        lambda _root: {
            "items": [
                {"symbol": "ZZZ", "quantity": 5.0},
                {"symbol": "AAA", "quantity": 0.0},
            ],
            "stale": False,
            "source_detail": "ib_holdings",
        },
        raising=False,
    )
    # Latest net liq says 20k, but run.params carries an older 10k value. Executor should use latest.
    monkeypatch.setattr(
        trade_executor,
        "fetch_account_summary",
        lambda _session: {"NetLiquidation": 20000.0, "cash_available": 1000.0},
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

    session = Session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={}))
        session.commit()

        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path, symbol="AAA", weight=0.1)
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
            params={
                "order_type": "MKT",
                "risk_bypass": True,
                "portfolio_value": 10000.0,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        trade_executor.execute_trade_run(run.id, dry_run=True, force=False)

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}

        # Must update sizing PV from latest NetLiquidation for traceability.
        assert float(params.get("portfolio_value") or 0.0) == 20000.0

        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        )
        assert len(orders) == 2
        assert orders[0].symbol == "ZZZ"
        assert orders[0].side == "SELL"
        assert float(orders[0].quantity or 0.0) == 5.0

        assert orders[1].symbol == "AAA"
        assert orders[1].side == "BUY"
        # target_qty = ceil(0.1 * 20000 / 100) = 20
        assert float(orders[1].quantity or 0.0) == 20.0

        intent_path = params.get("order_intent_path")
        assert intent_path
        payload = json.loads(Path(str(intent_path)).read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert payload[0]["symbol"] == "ZZZ"
        assert float(payload[0]["quantity"]) == -5.0
        assert payload[1]["symbol"] == "AAA"
        assert float(payload[1]["quantity"]) == 20.0

        exec_params_path = params.get("execution_params_path")
        assert exec_params_path
        exec_params = json.loads(Path(str(exec_params_path)).read_text(encoding="utf-8"))
        assert isinstance(exec_params, dict)
        # Long-unfilled policy must be present so Lean can stay alive and manage cancels/reprices.
        assert "unfilled_timeout_seconds" in exec_params
        assert "unfilled_reprice_interval_seconds" in exec_params
        assert "unfilled_max_reprices" in exec_params
        assert "unfilled_max_price_deviation_pct" in exec_params
    finally:
        session.close()


def test_execute_trade_run_adaptive_intent_writes_prime_price(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 123.45}], "stale": False},
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "read_positions",
        lambda _root: {"items": [], "stale": False, "source_detail": "ib_holdings"},
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "fetch_account_summary",
        lambda _session: {"NetLiquidation": 10000.0, "cash_available": 10000.0},
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

    session = Session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={}))
        session.commit()

        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        items_path = tmp_path / "decision_items.csv"
        _write_items(items_path, symbol="AAA", weight=0.1)
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
            params={
                "order_type": "ADAPTIVE_LMT",
                "risk_bypass": True,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        trade_executor.execute_trade_run(run.id, dry_run=True, force=False)

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}
        intent_path = params.get("order_intent_path")
        assert intent_path
        payload = json.loads(Path(str(intent_path)).read_text(encoding="utf-8"))
        assert isinstance(payload, list) and payload
        assert payload[0]["order_type"] == "ADAPTIVE_LMT"
        assert payload[0].get("limit_price") is None
        assert float(payload[0]["prime_price"]) == 123.45
    finally:
        session.close()
