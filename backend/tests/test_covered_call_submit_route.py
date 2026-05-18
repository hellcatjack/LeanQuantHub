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


def test_covered_call_submit_route_rejects_live_mode(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = trade_routes.CoveredCallSubmitRequest(
            mode="live",
            symbol="AAPL",
            review_id="review-1",
            approval_token="token-1",
            dry_run=False,
        )
        with pytest.raises(Exception) as exc_info:
            trade_routes.submit_covered_call_route(payload)
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "paper_only" in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_submit_route_rejects_blank_review_and_token(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = trade_routes.CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id="",
            approval_token="",
            dry_run=False,
        )
        with pytest.raises(Exception) as exc_info:
            trade_routes.submit_covered_call_route(payload)
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "review_id_required" in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_submit_route_returns_service_payload(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        called = {}

        def _fake_submit(session_obj, payload):
            called["same_session"] = session_obj is session
            called["review_id"] = payload.review_id
            return {
                "mode": "paper",
                "status": "submitted",
                "gate_reason": None,
                "review_id": "review-1",
                "command_id": "submit_order_cc_1",
                "command_result_status": "submitted",
                "runtime_summary": {"state": "healthy"},
                "position_summary": {"shares": 200},
                "open_orders_summary": {"symbol_conflict": False},
                "artifacts": {"summary": "/tmp/summary.json"},
            }

        monkeypatch.setattr(trade_routes, "build_covered_call_submit", _fake_submit)
        payload = trade_routes.CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id="review-1",
            approval_token="token-1",
            dry_run=False,
        )
        result = trade_routes.submit_covered_call_route(payload)
        assert called == {"same_session": True, "review_id": "review-1"}
        assert result["status"] == "submitted"
        assert result["command_id"] == "submit_order_cc_1"
    finally:
        session.close()
