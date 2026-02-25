from pathlib import Path
import sys
import csv
import json
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


def _write_price_file(path: Path, symbol: str, close_price: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "open", "high", "low", "close", "volume", "symbol"])
        writer.writeheader()
        writer.writerow(
            {
                "date": "2026-01-29",
                "open": close_price,
                "high": close_price,
                "low": close_price,
                "close": close_price,
                "volume": 100,
                "symbol": symbol,
            }
        )


def test_execute_builds_orders_from_snapshot(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {
            "items": [
                {"symbol": "AAA", "last": 50},
                {"symbol": "BBB", "last": 25},
            ],
            "stale": False,
        },
        raising=False,
    )
    monkeypatch.setattr(
        trade_executor,
        "read_positions",
        lambda _root: {"items": [], "stale": False},
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


def test_execute_blocks_when_execution_source_not_lean(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 50}], "stale": False},
        raising=False,
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


def test_execute_builds_orders_with_fallback_prices(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {
            "items": [
                {"symbol": "AAA", "last": 0.0},
                {"symbol": "BBB", "last": 0.0},
            ],
            "stale": False,
        },
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
    monkeypatch.setattr(trade_executor.settings, "data_root", str(tmp_path))

    adjusted_dir = tmp_path / "curated_adjusted"
    _write_price_file(adjusted_dir / "1_Alpha_AAA_Daily.csv", "AAA", 50)
    _write_price_file(adjusted_dir / "2_Alpha_BBB_Daily.csv", "BBB", 25)

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


def test_build_orders_rounding():
    items = [{"symbol": "SPY", "weight": 0.1}]
    price_map = {"SPY": 60}
    orders = build_orders(items, price_map=price_map, portfolio_value=1000)
    assert orders[0]["quantity"] == 2


def test_execute_blocks_when_guard_precheck_halted(monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)

    def _fake_guard_eval(session, *, project_id, mode, risk_params=None, **_kwargs):
        state = trade_executor.get_or_create_guard_state(
            session,
            project_id=project_id,
            mode=mode,
        )
        state.status = "halted"
        state.halt_reason = {
            "reasons": ["max_daily_loss"],
            "details": [{"reason": "max_daily_loss", "value": -0.07, "threshold": -0.05}],
        }
        session.commit()
        return {
            "status": "halted",
            "reason": state.halt_reason,
            "valuation_source": "test",
            "equity": 0.0,
            "thresholds": {"max_daily_loss": -0.05, "max_intraday_drawdown": 0.08, "cooldown_seconds": 900},
            "metrics": {"daily_loss": -0.07, "drawdown": -0.08},
            "trigger_details": [{"reason": "max_daily_loss", "value": -0.07, "threshold": -0.05}],
        }

    monkeypatch.setattr(trade_executor, "evaluate_intraday_guard", _fake_guard_eval, raising=False)

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
            params={},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True, force=False)
        assert result.status == "blocked"
        assert result.message == "guard_halted"

        session.expire_all()
        refreshed = session.get(TradeRun, run.id)
        assert refreshed is not None
        params = refreshed.params if isinstance(refreshed.params, dict) else {}
        precheck = params.get("guard_precheck") if isinstance(params, dict) else {}
        assert isinstance(precheck, dict)
        assert precheck.get("enabled") is True
        assert precheck.get("status") == "halted"
        assert precheck.get("thresholds", {}).get("max_daily_loss") == -0.05
        blocked = params.get("guard_blocked") if isinstance(params, dict) else {}
        assert isinstance(blocked, dict)
        assert blocked.get("valuation_source") == "test"
        assert "max_daily_loss" in ((blocked.get("reason") or {}).get("reasons") or [])
    finally:
        session.close()


def test_execute_blocks_when_guard_precheck_degraded(monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)

    def _fake_guard_eval(session, *, project_id, mode, risk_params=None, **_kwargs):
        state = trade_executor.get_or_create_guard_state(
            session,
            project_id=project_id,
            mode=mode,
        )
        state.status = "active"
        state.halt_reason = None
        session.commit()
        return {
            "status": "degraded",
            "reason": {
                "reasons": ["valuation_unreliable"],
                "details": [{"reason": "equity_non_positive", "value": 0.0, "threshold": 0.0}],
            },
            "valuation_source": "lean_bridge",
            "equity": 0.0,
            "equity_source": "local:lean_bridge",
            "thresholds": {"max_daily_loss": -0.05, "max_intraday_drawdown": 0.08, "cooldown_seconds": 900},
            "metrics": {"equity_adjusted": 0.0, "market_data_errors": 99},
            "trigger_details": [],
        }

    monkeypatch.setattr(trade_executor, "evaluate_intraday_guard", _fake_guard_eval, raising=False)

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
            params={},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        result = trade_executor.execute_trade_run(run.id, dry_run=True, force=False)
        assert result.status == "blocked"
        assert result.message == "guard_data_unreliable"

        session.expire_all()
        refreshed = session.get(TradeRun, run.id)
        assert refreshed is not None
        params = refreshed.params if isinstance(refreshed.params, dict) else {}
        precheck = params.get("guard_precheck") if isinstance(params, dict) else {}
        assert isinstance(precheck, dict)
        assert precheck.get("status") == "degraded"
        blocked = params.get("guard_blocked") if isinstance(params, dict) else {}
        assert isinstance(blocked, dict)
        assert blocked.get("status") == "degraded"
    finally:
        session.close()


def test_execute_rewrites_intent_ids_when_missing(tmp_path, monkeypatch):
    Session = _make_session_factory()
    monkeypatch.setattr(trade_executor, "SessionLocal", Session)
    monkeypatch.setattr(trade_executor, "_bridge_connection_ok", lambda *_a, **_k: True, raising=False)
    monkeypatch.setattr(trade_executor.settings, "data_root", str(tmp_path), raising=False)
    monkeypatch.setattr(
        trade_executor,
        "read_quotes",
        lambda _root: {"items": [{"symbol": "AAA", "last": 50}], "stale": False},
        raising=False,
    )
    monkeypatch.setattr(trade_executor, "fetch_account_summary", lambda *_a, **_k: {"NetLiquidation": 10000})
    monkeypatch.setattr(trade_executor, "launch_execution_async", lambda **_kwargs: 123)

    intent_path = tmp_path / "intent.json"
    intent_path.write_text('[{"symbol":"AAA","weight":0.1}]', encoding="utf-8")

    session = Session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path=str(tmp_path / "items.csv"))
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            status="queued",
            mode="paper",
            params={"order_intent_path": str(intent_path), "portfolio_value": 10000},
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="test:AAA:BUY",
            symbol="AAA",
            side="BUY",
            quantity=1,
            order_type="MKT",
        )
        session.add(order)
        session.commit()

        result = trade_executor.execute_trade_run(run.id, dry_run=False, force=True)
        assert result.status in {"running", "done", "blocked", "failed", "queued"}
        payload = json.loads(intent_path.read_text(encoding="utf-8"))
        assert payload[0].get("order_intent_id")
    finally:
        session.close()


def test_build_guard_alert_message_includes_drawdown_thresholds():
    message = trade_executor._build_guard_alert_message(
        42,
        {
            "reason": {"reasons": ["max_drawdown"]},
            "valuation_source": "lean_bridge",
            "equity_source": "ib_net_liquidation",
            "thresholds": {
                "max_daily_loss": -0.05,
                "max_intraday_drawdown": 0.08,
                "max_drawdown": 0.12,
                "max_drawdown_52w": 0.15,
                "drawdown_recovery_ratio": 0.9,
                "cooldown_seconds": 900,
            },
        },
    )
    assert "max_drawdown=0.12" in message
    assert "max_drawdown_52w=0.15" in message
    assert "drawdown_recovery_ratio=0.9" in message
