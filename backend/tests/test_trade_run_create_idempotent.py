from contextlib import contextmanager
from pathlib import Path
import sys
from datetime import datetime

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.routes.trade as trade_routes
from app.schemas import TradeRunCreate, TradeRunExecuteRequest
from app.models import Base, Project, DecisionSnapshot, TradeRun, TradeSettings


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_trade_run_idempotent(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path="/tmp/x.csv")
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "check_market_health", lambda *_a, **_k: {"status": "ok"})

        payload = TradeRunCreate(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            orders=[],
            require_market_health=False,
        )
        first = trade_routes.create_trade_run(payload)
        second = trade_routes.create_trade_run(payload)
        assert first.id == second.id

        run = session.get(TradeRun, first.id)
        run.status = "partial"
        run.ended_at = datetime.utcnow()
        session.commit()

        third = trade_routes.create_trade_run(payload)
        assert third.id != first.id

        run = session.get(TradeRun, third.id)
        run.status = "failed"
        run.ended_at = datetime.utcnow()
        session.commit()

        fourth = trade_routes.create_trade_run(payload)
        assert fourth.id != third.id
    finally:
        session.close()


def test_trade_run_deadband_defaults_support_global_and_run_override(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path="/tmp/x.csv")
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        settings = TradeSettings(
            risk_defaults={
                "deadband_min_notional": 1500.0,
                "deadband_min_weight": 0.02,
            },
            execution_data_source="lean",
        )
        session.add(settings)
        session.commit()

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "check_market_health", lambda *_a, **_k: {"status": "ok"})

        base_payload = TradeRunCreate(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            orders=[],
            require_market_health=False,
        )
        created = trade_routes.create_trade_run(base_payload)
        created_run = session.get(TradeRun, created.id)
        params = created_run.params if isinstance(created_run.params, dict) else {}
        assert float(params.get("deadband_min_notional") or 0.0) == 1500.0
        assert float(params.get("deadband_min_weight") or 0.0) == 0.02

        # Move previous run to terminal so idempotency allows creating a new run.
        created_run.status = "partial"
        created_run.ended_at = datetime.utcnow()
        session.commit()

        override_payload = TradeRunCreate(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="paper",
            orders=[],
            require_market_health=False,
            deadband_min_notional=3500.0,
            deadband_min_weight=0.03,
        )
        overridden = trade_routes.create_trade_run(override_payload)
        overridden_run = session.get(TradeRun, overridden.id)
        overridden_params = overridden_run.params if isinstance(overridden_run.params, dict) else {}
        assert float(overridden_params.get("deadband_min_notional") or 0.0) == 3500.0
        assert float(overridden_params.get("deadband_min_weight") or 0.0) == 0.03
    finally:
        session.close()


def test_live_confirm_required(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        snapshot = DecisionSnapshot(project_id=project.id, status="success", items_path="/tmp/x.csv")
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "check_market_health", lambda *_a, **_k: {"status": "ok"})

        payload = TradeRunCreate(
            project_id=project.id,
            decision_snapshot_id=snapshot.id,
            mode="live",
            orders=[],
            require_market_health=False,
        )
        try:
            trade_routes.create_trade_run(payload)
        except Exception as exc:
            assert "live_confirm_required" in str(exc)
    finally:
        session.close()


def test_execute_requires_live_confirm(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(project_id=project.id, decision_snapshot_id=1, mode="live", status="queued", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = TradeRunExecuteRequest(dry_run=True, force=False, live_confirm_token=None)
        try:
            trade_routes.execute_trade_run_route(run.id, payload)
        except Exception as exc:
            assert "live_confirm_required" in str(exc)
    finally:
        session.close()


def test_execute_blocks_when_current_positions_not_precise(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(project_id=project.id, decision_snapshot_id=1, mode="paper", status="queued", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        @contextmanager
        def _get_session():
            yield session

        class _Result:
            run_id = run.id
            status = "blocked"
            filled = 0
            cancelled = 0
            rejected = 0
            skipped = 0
            message = "current_positions_not_precise"
            dry_run = False

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "execute_trade_run", lambda *_args, **_kwargs: _Result())

        payload = TradeRunExecuteRequest(dry_run=False, force=False, live_confirm_token=None)
        try:
            trade_routes.execute_trade_run_route(run.id, payload)
            assert False, "expected HTTPException"
        except Exception as exc:
            assert "current_positions_not_precise" in str(exc)
    finally:
        session.close()


def test_execute_rejects_risk_off_drill_without_dry_run(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="p", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(project_id=project.id, decision_snapshot_id=1, mode="paper", status="queued", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = TradeRunExecuteRequest(
            dry_run=False,
            force=False,
            live_confirm_token=None,
            risk_off_drill=True,
        )
        try:
            trade_routes.execute_trade_run_route(run.id, payload)
            assert False, "expected HTTPException"
        except Exception as exc:
            assert "risk_off_drill_requires_dry_run" in str(exc)
    finally:
        session.close()
