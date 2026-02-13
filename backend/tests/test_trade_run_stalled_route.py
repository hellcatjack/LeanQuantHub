from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Project, TradeOrder, TradeRun
from app.schemas import TradeRunActionRequest
from app.services import trade_executor
import app.routes.trade as trade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _seed_project(session):
    project = Project(name="p", description="")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def test_refresh_trade_run_marks_stalled(monkeypatch):
    session = _make_session()
    try:
        project = _seed_project(session)
        now = datetime.utcnow()
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=None,
            mode="paper",
            status="running",
            last_progress_at=now - timedelta(minutes=20),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        monkeypatch.setattr(trade_executor, "is_market_open", lambda *_a, **_k: True)
        updated = trade_executor.refresh_trade_run_status(session, run)
        assert updated is True
        assert run.status == "stalled"
        assert run.stalled_at is not None
    finally:
        session.close()


def test_refresh_trade_run_marks_failed_when_no_orders_submitted(monkeypatch):
    session = _make_session()
    try:
        project = _seed_project(session)
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order_a = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1032_1",
            symbol="AAPL",
            side="BUY",
            quantity=10,
            status="NEW",
        )
        order_b = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1032_2",
            symbol="MSFT",
            side="BUY",
            quantity=5,
            status="NEW",
        )
        session.add_all([order_a, order_b])
        session.commit()

        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_a, **_k: True)
        updated = trade_executor.refresh_trade_run_status(session, run)
        assert updated is True
        assert run.status == "failed"
        assert run.message == "no_orders_submitted"
        assert run.ended_at is not None

        orders = session.query(TradeOrder).filter(TradeOrder.run_id == run.id).all()
        assert orders
        assert all(order.status == "CANCELED" for order in orders)
    finally:
        session.close()


def test_refresh_trade_run_marks_already_held_from_positions(monkeypatch):
    session = _make_session()
    try:
        project = _seed_project(session)
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order_a = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1032_1",
            symbol="AAPL",
            side="BUY",
            quantity=10,
            status="NEW",
        )
        order_b = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1032_2",
            symbol="MSFT",
            side="BUY",
            quantity=5,
            status="NEW",
        )
        session.add_all([order_a, order_b])
        session.commit()

        monkeypatch.setattr(
            trade_executor,
            "read_positions",
            lambda *_a, **_k: {
                "stale": False,
                "items": [
                    {"symbol": "AAPL", "quantity": 10, "avg_cost": 100.0},
                ],
            },
        )
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_a, **_k: True)
        updated = trade_executor.refresh_trade_run_status(session, run)
        assert updated is True
        assert run.status == "failed"
        assert run.message == "no_orders_submitted"
        assert run.params.get("already_held_orders") == ["AAPL"]

        refreshed_a = session.query(TradeOrder).filter(TradeOrder.symbol == "AAPL").one()
        refreshed_b = session.query(TradeOrder).filter(TradeOrder.symbol == "MSFT").one()
        assert refreshed_a.status == "FILLED"
        assert refreshed_a.params.get("already_held") is True
        assert refreshed_b.status == "CANCELED"
    finally:
        session.close()


def test_refresh_trade_run_marks_stalled_when_submit_command_pending_timeout(monkeypatch):
    session = _make_session()
    try:
        project = _seed_project(session)
        now = datetime.utcnow()
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=1,
            mode="paper",
            status="running",
            last_progress_at=now - timedelta(minutes=1),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        order = TradeOrder(
            run_id=run.id,
            client_order_id="oi_1200_1",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            order_type="ADAPTIVE_LMT",
            status="NEW",
            params={
                "event_tag": "oi_1200_1",
                "submit_command": {
                    "pending": True,
                    "command_id": "submit_order_1200_1",
                    "requested_at": (now - timedelta(seconds=120)).isoformat() + "Z",
                },
            },
        )
        session.add(order)
        session.commit()

        monkeypatch.setattr(
            trade_executor,
            "read_open_orders",
            lambda *_a, **_k: {"items": [], "stale": True},
        )
        monkeypatch.setattr(
            trade_executor,
            "read_positions",
            lambda *_a, **_k: {"items": [], "stale": True},
        )
        monkeypatch.setattr(trade_executor, "_lean_no_orders_submitted", lambda *_a, **_k: False)
        monkeypatch.setattr(trade_executor, "is_market_open", lambda *_a, **_k: True)

        updated = trade_executor.refresh_trade_run_status(session, run)
        assert updated is True
        assert run.status == "stalled"
        assert run.stalled_reason == "submit_command_pending_timeout"
        assert run.stalled_at is not None
    finally:
        session.close()


def test_resume_and_terminate_trade_run(monkeypatch):
    session = _make_session()
    try:
        project = _seed_project(session)
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=None,
            mode="paper",
            status="stalled",
            stalled_at=datetime.utcnow(),
            stalled_reason="no_progress",
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)

        resumed = trade_routes.resume_trade_run(run.id, TradeRunActionRequest(reason="manual"))
        assert resumed.status == "running"
        refreshed = session.get(TradeRun, run.id)
        assert refreshed.stalled_at is None

        terminated = trade_routes.terminate_trade_run(run.id, TradeRunActionRequest(reason="manual stop"))
        assert terminated.status in {"failed", "canceled"}
        refreshed = session.get(TradeRun, run.id)
        assert refreshed.ended_at is not None
    finally:
        session.close()


def test_sync_trade_run(monkeypatch):
    session = _make_session()
    try:
        project = _seed_project(session)
        run = TradeRun(
            project_id=project.id,
            decision_snapshot_id=None,
            mode="paper",
            status="running",
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_executor, "is_market_open", lambda *_a, **_k: True)
        result = trade_routes.sync_trade_run(run.id)
        assert result.id == run.id
    finally:
        session.close()
