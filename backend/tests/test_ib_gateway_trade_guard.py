from contextlib import contextmanager
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, Project, TradeOrder, TradeRun
from app.routes import trade as trade_routes
from app.schemas import TradeDirectOrderRequest, TradeRunExecuteRequest
from app.services import manual_trade_execution, trade_direct_order, trade_executor
from app.services.trade_orders import create_trade_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_submit_direct_order_blocks_when_gateway_degraded(monkeypatch):
    payload = {
        "project_id": 18,
        "mode": "paper",
        "client_order_id": "manual-guard-1",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "order_type": "MKT",
        "params": {"source": "manual", "project_id": 18},
    }

    monkeypatch.setattr(trade_direct_order, "get_gateway_trade_block_state", lambda _root: "gateway_degraded")

    with pytest.raises(ValueError, match="gateway_degraded"):
        trade_direct_order.submit_direct_order(object(), payload)


def test_execute_manual_order_blocks_when_gateway_restarting(monkeypatch):
    session = _make_session()
    try:
        order = create_trade_order(
            session,
            {
                "client_order_id": "oi_guard_manual_1",
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 1,
                "order_type": "MKT",
            },
        ).order
        session.commit()

        monkeypatch.setattr(
            manual_trade_execution,
            "get_gateway_trade_block_state",
            lambda _root: "gateway_restarting",
        )

        with pytest.raises(ValueError, match="gateway_restarting"):
            manual_trade_execution.execute_manual_order(session, order, project_id=12, mode="paper")
    finally:
        session.close()


def test_execute_trade_run_blocks_when_gateway_restarting(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="guard", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = TradeRun(project_id=project.id, decision_snapshot_id=1, mode="paper", status="queued", params={})
        session.add(run)
        session.commit()
        session.refresh(run)

        monkeypatch.setattr(trade_executor, "SessionLocal", lambda: session)
        monkeypatch.setattr(trade_executor, "get_gateway_trade_block_state", lambda _root: "gateway_restarting")

        with pytest.raises(RuntimeError, match="gateway_restarting"):
            trade_executor.execute_trade_run(run.id, dry_run=True)
    finally:
        session.close()


def test_direct_order_route_maps_gateway_degraded_to_409(monkeypatch):
    @contextmanager
    def _get_session():
        yield None

    monkeypatch.setattr(trade_routes, "get_session", _get_session)
    monkeypatch.setattr(trade_routes, "submit_direct_order", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("gateway_degraded")))

    payload = TradeDirectOrderRequest(
        project_id=18,
        mode="paper",
        client_order_id="manual-route-1",
        symbol="AAPL",
        side="BUY",
        quantity=1,
        order_type="MKT",
        params={"source": "manual", "project_id": 18},
    )

    with pytest.raises(HTTPException) as exc_info:
        trade_routes.create_direct_trade_order_route(payload)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "gateway_degraded"


def test_execute_trade_run_route_maps_gateway_restarting_to_409(monkeypatch):
    session = _make_session()
    try:
        project = Project(name="route", description="")
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
        monkeypatch.setattr(
            trade_routes,
            "execute_trade_run",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("gateway_restarting")),
        )

        payload = TradeRunExecuteRequest(dry_run=False, force=False, live_confirm_token=None)

        with pytest.raises(HTTPException) as exc_info:
            trade_routes.execute_trade_run_route(run.id, payload)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "gateway_restarting"
    finally:
        session.close()
