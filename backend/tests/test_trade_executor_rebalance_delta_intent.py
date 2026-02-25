from __future__ import annotations

from pathlib import Path
import csv
import json
import sys

import pytest
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
    monkeypatch.setattr(
        trade_executor,
        "get_account_positions",
        lambda _session, *, mode, force_refresh=False: {
            "items": [
                {"symbol": "ZZZ", "quantity": 5.0},
                {"symbol": "AAA", "quantity": 0.0},
            ],
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
            "refreshed_at": "2026-02-14T00:00:00Z",
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
        "get_account_positions",
        lambda _session, *, mode, force_refresh=False: {
            "items": [],
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
            "refreshed_at": "2026-02-14T00:00:00Z",
        },
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


def test_execute_trade_run_deadband_filters_small_orders_and_completes_noop(tmp_path, monkeypatch):
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
            "refreshed_at": "2026-02-14T00:00:00Z",
        },
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

        # target_qty = ceil(0.1 * 10000 / 100) = 10 -> order notional = 1000
        # deadband_min_notional=2000 should filter this order, resulting in no-op done run.
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            status="queued",
            mode="paper",
            params={
                "order_type": "MKT",
                "risk_bypass": True,
                "deadband_min_notional": 2000.0,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        trade_executor.execute_trade_run(run.id, dry_run=True, force=False)

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.status == "done"
        assert refreshed_run.message == "no_orders_required"
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}
        summary = params.get("completion_summary") if isinstance(params.get("completion_summary"), dict) else {}
        assert summary.get("no_orders_required") is True

        orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        assert orders == []
    finally:
        session.close()


def test_execute_trade_run_uses_trade_settings_deadband_defaults_when_run_missing(tmp_path, monkeypatch):
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
            "refreshed_at": "2026-02-14T00:00:00Z",
        },
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
        session.add(
            TradeSettings(
                risk_defaults={
                    "deadband_min_notional": 2000.0,
                    "deadband_min_weight": 0.0,
                },
                execution_data_source="lean",
                auto_recovery={},
            )
        )
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

        # run.params omits deadband; global settings deadband should still apply.
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            status="queued",
            mode="paper",
            params={
                "order_type": "MKT",
                "risk_bypass": True,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        trade_executor.execute_trade_run(run.id, dry_run=True, force=False)

        session.expire_all()
        refreshed_run = session.get(TradeRun, run.id)
        assert refreshed_run is not None
        assert refreshed_run.status == "done"
        assert refreshed_run.message == "no_orders_required"
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}
        assert float(params.get("deadband_min_notional") or 0.0) == 2000.0
        assert float(params.get("deadband_min_weight") or 0.0) == 0.0
        summary = params.get("completion_summary") if isinstance(params.get("completion_summary"), dict) else {}
        assert summary.get("no_orders_required") is True

        orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        assert orders == []
    finally:
        session.close()


def test_execute_trade_run_blocks_when_current_positions_not_precise(tmp_path, monkeypatch):
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
        "get_account_positions",
        lambda _session, *, mode, force_refresh=False: {
            "items": [{"symbol": "AAA", "quantity": 1.0}],
            "stale": True,
            "source_detail": "ib_holdings",
            "refreshed_at": "2026-02-14T00:00:00Z",
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
            params={"order_type": "MKT"},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True, force=False)
        assert result.status == "blocked"
        assert result.message == "current_positions_not_precise"

        session.expire_all()
        refreshed = session.get(TradeRun, run.id)
        assert refreshed is not None
        assert refreshed.status == "blocked"
        assert refreshed.message == "current_positions_not_precise"
    finally:
        session.close()


def test_execute_trade_run_risk_off_drill_uses_defensive_basket_only(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {
            "items": [
                {"symbol": "AAA", "last": 100.0},
                {"symbol": "VGSH", "last": 100.0},
                {"symbol": "IEF", "last": 100.0},
                {"symbol": "GLD", "last": 100.0},
                {"symbol": "TLT", "last": 100.0},
            ],
            "stale": False,
        },
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "get_account_positions",
        lambda _session, *, mode, force_refresh=False: {
            "items": [{"symbol": "AAA", "quantity": 5.0}],
            "stale": False,
            "source_detail": "ib_holdings_ibapi_fallback",
            "refreshed_at": "2026-02-14T00:00:00Z",
        },
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
        _write_items(items_path, symbol="AAA", weight=0.6)
        snapshot = DecisionSnapshot(
            project_id=project.id,
            status="success",
            items_path=str(items_path),
            summary={
                "algorithm_parameters": {"risk_off_symbols": "VGSH,IEF,GLD,TLT"},
                "effective_exposure_cap": 0.4,
                "max_exposure": 1.0,
            },
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
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True, force=False, risk_off_drill=True)
        assert result.status == "done"

        session.expire_all()
        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        )
        order_symbols = [str(order.symbol or "").upper() for order in orders]
        assert set(order_symbols) == {"AAA", "VGSH", "IEF", "GLD", "TLT"}
        assert {order.side for order in orders if order.symbol == "AAA"} == {"SELL"}

        for symbol in ("VGSH", "IEF", "GLD", "TLT"):
            symbol_orders = [order for order in orders if order.symbol == symbol]
            assert len(symbol_orders) == 1
            assert symbol_orders[0].side == "BUY"
            assert float(symbol_orders[0].quantity or 0.0) == 10.0

        refreshed_run = session.get(TradeRun, run.id)
        params = refreshed_run.params if isinstance(refreshed_run.params, dict) else {}
        drill_meta = params.get("risk_off_drill") if isinstance(params.get("risk_off_drill"), dict) else {}
        assert drill_meta.get("enabled") is True
        assert float(drill_meta.get("exposure_cap") or 0.0) == 0.4
        assert set(drill_meta.get("symbols") or []) == {"VGSH", "IEF", "GLD", "TLT"}
    finally:
        session.close()


def test_execute_trade_run_risk_off_drill_requires_dry_run(monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)

    with pytest.raises(RuntimeError, match="risk_off_drill_requires_dry_run"):
        trade_executor.execute_trade_run(1, dry_run=False, force=False, risk_off_drill=True)
