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
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _write_items(path: Path, *, symbol: str, weight: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "weight", "score", "rank"])
        writer.writeheader()
        writer.writerow({"symbol": symbol, "weight": str(weight), "score": "1.0", "rank": "1"})


def test_execute_trade_run_cash_guard_shrinks_buys_even_when_risk_bypassed(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "get_gateway_trade_block_state",
        lambda *_a, **_k: None,
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 100.0}], "stale": False},
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
        "get_account_positions",
        lambda _session, *, mode, force_refresh=False: {
            "items": [],
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
            "refreshed_at": "2026-04-24T00:00:00Z",
        },
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "fetch_account_summary",
        lambda _session: {"NetLiquidation": 10_000.0, "cash_available": 950.0},
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
        _write_items(items_path, symbol="AAA", weight=0.2)
        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path=str(items_path))
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
                "portfolio_value": 10_000.0,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True, force=False)

        assert result.status == "done"
        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        )
        assert len(orders) == 1
        assert orders[0].symbol == "AAA"
        assert orders[0].side == "BUY"
        assert float(orders[0].quantity or 0.0) == 9.0

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}
        cash_guard = params.get("cash_guard")
        assert cash_guard["applied"] is True
        assert cash_guard["estimated_buy_cost_before"] == 2000.0
        assert cash_guard["estimated_buy_cost_after"] == 900.0
        assert cash_guard["adjustments"][0]["action"] == "reduced"

        intent_path = params.get("order_intent_path")
        payload = json.loads(Path(str(intent_path)).read_text(encoding="utf-8"))
        assert float(payload[0]["quantity"]) == 9.0
    finally:
        session.close()


def test_execute_trade_run_cash_guard_uses_fresh_true_cash_over_stale_available_funds(
    tmp_path, monkeypatch
):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "get_gateway_trade_block_state",
        lambda *_a, **_k: None,
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 100.0}], "stale": False},
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
        "get_account_positions",
        lambda _session, *, mode, force_refresh=False: {
            "items": [],
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
            "refreshed_at": "2026-04-24T00:00:00Z",
        },
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "fetch_account_summary",
        lambda _session: {
            "NetLiquidation": 10_000.0,
            "AvailableFunds": 25_000.0,
            "CashBalance": -100.0,
            "TotalCashValue": -99.5,
            "cash_available": -100.0,
            "cash_available_source": "CashBalance",
        },
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
        _write_items(items_path, symbol="AAA", weight=0.2)
        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path=str(items_path))
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
                "portfolio_value": 10_000.0,
                "cash_available": 25_000.0,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True, force=False)

        assert result.status == "blocked"
        assert result.message == "cash_budget_insufficient"
        orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        assert orders == []

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}
        assert params["cash_available"] == -100.0
        assert params["cash_available_source"] == "CashBalance"
        assert params["cash_guard"]["cash_budget"] == 0.0
        assert params["cash_guard"]["blocked_no_orders"] is True
        assert params["cash_guard"]["adjustments"][0]["action"] == "skipped"
    finally:
        session.close()


def test_execute_trade_run_cash_guard_blocks_existing_orders_even_when_risk_bypassed(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "get_gateway_trade_block_state",
        lambda *_a, **_k: None,
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "_build_price_map", lambda _symbols: {"AAA": 100.0}, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "fetch_account_summary",
        lambda _session: {"NetLiquidation": 10_000.0, "cash_available": 500.0},
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "ARTIFACT_ROOT", tmp_path, raising=False)

    session = Session()
    try:
        session.add(TradeSettings(risk_defaults={}, execution_data_source="lean", auto_recovery={}))
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=1,
            status="queued",
            mode="paper",
            params={
                "risk_bypass": True,
                "portfolio_value": 10_000.0,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add(
            TradeOrder(
                run_id=run.id,
                client_order_id="existing:1",
                symbol="AAA",
                side="BUY",
                quantity=10.0,
                order_type="MKT",
                status="NEW",
            )
        )
        session.commit()

        result = trade_executor.execute_trade_run(run.id, dry_run=True, force=False)

        assert result.status == "blocked"
        assert result.message == "cash_budget"
        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}
        assert params["cash_guard_submit_blocked"]["reasons"] == ["cash_budget"]
    finally:
        session.close()
