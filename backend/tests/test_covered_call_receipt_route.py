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


def test_covered_call_receipt_route_rejects_live_mode(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = trade_routes.CoveredCallReceiptRequest(
            mode="live",
            review_id="review-1",
            command_id="cmd-1",
        )
        with pytest.raises(Exception) as exc_info:
            trade_routes.get_covered_call_receipt_route(payload)
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "paper_only" in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_receipt_route_rejects_blank_ids(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = trade_routes.CoveredCallReceiptRequest(
            mode="paper",
            review_id="",
            command_id="",
        )
        with pytest.raises(Exception) as exc_info:
            trade_routes.get_covered_call_receipt_route(payload)
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "review_id_required" in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_receipt_route_returns_service_payload(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        called = {}

        def _fake_receipt(session_obj, payload):
            called["same_session"] = session_obj is session
            called["review_id"] = payload.review_id
            called["command_id"] = payload.command_id
            return {
                "mode": "paper",
                "status": "submitted",
                "receipt_state": "open_confirmed",
                "gate_reason": None,
                "review_id": "review-1",
                "command_id": "cmd-1",
                "command_result_status": "submitted",
                "runtime_summary": {"state": "healthy"},
                "open_orders_summary": {"matched_count": 1},
                "artifacts": {"summary": "/tmp/summary.json"},
            }

        monkeypatch.setattr(trade_routes, "build_covered_call_receipt", _fake_receipt)
        payload = trade_routes.CoveredCallReceiptRequest(
            mode="paper",
            review_id="review-1",
            command_id="cmd-1",
        )
        result = trade_routes.get_covered_call_receipt_route(payload)
        assert called == {"same_session": True, "review_id": "review-1", "command_id": "cmd-1"}
        assert result["status"] == "submitted"
        assert result["receipt_state"] == "open_confirmed"
    finally:
        session.close()
