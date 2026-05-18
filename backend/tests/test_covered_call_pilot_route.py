from contextlib import contextmanager
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.routes import trade as trade_routes


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_covered_call_pilot_route_rejects_live_mode(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = trade_routes.CoveredCallPilotRequest(mode="live", dry_run=True)
        with pytest.raises(Exception) as exc_info:
            trade_routes.run_covered_call_pilot_route(payload)
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "paper_only" in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_pilot_route_rejects_non_dry_run(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = trade_routes.CoveredCallPilotRequest(mode="paper", dry_run=False)
        with pytest.raises(Exception) as exc_info:
            trade_routes.run_covered_call_pilot_route(payload)
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "dry_run_only" in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_pilot_route_returns_service_payload(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        called = {}

        def _fake_run(session_obj, payload):
            called["same_session"] = session_obj is session
            called["mode"] = payload.mode
            return {
                "mode": "paper",
                "status": "ok",
                "eligible": [],
                "rejected": [{"symbol": "AAPL", "reason": "shares_below_100"}],
                "artifacts": {"summary": "/tmp/summary.json", "orders": "/tmp/dry_run_orders.json"},
            }

        monkeypatch.setattr(trade_routes, "run_covered_call_pilot", _fake_run)
        payload = trade_routes.CoveredCallPilotRequest(mode="paper", dry_run=True)
        result = trade_routes.run_covered_call_pilot_route(payload)
        assert called == {"same_session": True, "mode": "paper"}
        assert result["status"] == "ok"
        assert result["rejected"][0]["symbol"] == "AAPL"
    finally:
        session.close()
