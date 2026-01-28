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

from app.models import Base
from app.routes import trade as trade_routes
from app.schemas import TradeOrderCreate


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_create_trade_order_triggers_manual_execution(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    calls = {"called": False}

    def _fake_execute(session, order, project_id, mode):
        calls["called"] = True
        return "/tmp/manual_order.json"

    monkeypatch.setattr(trade_routes, "get_session", _get_session)
    monkeypatch.setattr(trade_routes, "execute_manual_order", _fake_execute, raising=False)

    payload = TradeOrderCreate(
        client_order_id="oi_0_0_999",
        symbol="AAPL",
        side="BUY",
        quantity=1,
        order_type="MKT",
        params={"source": "manual", "project_id": 16, "mode": "paper"},
    )
    trade_routes.create_trade_order_route(payload)
    assert calls["called"] is True
    session.close()


def test_create_trade_order_manual_requires_project_id(monkeypatch):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    monkeypatch.setattr(trade_routes, "get_session", _get_session)

    payload = TradeOrderCreate(
        client_order_id="oi_0_0_1000",
        symbol="AAPL",
        side="BUY",
        quantity=1,
        order_type="MKT",
        params={"source": "manual"},
    )
    with pytest.raises(HTTPException) as excinfo:
        trade_routes.create_trade_order_route(payload)
    assert excinfo.value.status_code == 422
    session.close()
