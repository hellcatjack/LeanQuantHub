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
from app.models import Base, Project, DecisionSnapshot, TradeRun


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
