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


def test_recent_route_rejects_live_mode(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        payload = trade_routes.CoveredCallAuditRecentRequest(mode="live", limit=5)
        with pytest.raises(Exception) as exc_info:
            trade_routes.list_covered_call_audit_recent_route(payload)
        assert getattr(exc_info.value, "status_code", None) == 400
        assert "paper_only" in str(exc_info.value)
    finally:
        session.close()


def test_recent_route_returns_service_payload(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        called = {}

        def _fake_recent(session_obj, payload):
            called["same_session"] = session_obj is session
            called["limit"] = payload.limit
            called["offset"] = payload.offset
            called["query"] = payload.query
            return {
                "mode": "paper",
                "total": 1,
                "has_more": False,
                "items": [
                    {
                        "review_id": "review-1",
                        "symbol": "AAPL",
                        "status": "submitted",
                        "timeline_state": "submit_submitted",
                        "latest_command_id": "cmd-1",
                    }
                ],
            }

        monkeypatch.setattr(trade_routes, "list_covered_call_audit_recent", _fake_recent)
        payload = trade_routes.CoveredCallAuditRecentRequest(mode="paper", limit=5, offset=10, query="amd")
        result = trade_routes.list_covered_call_audit_recent_route(payload)
        assert called == {"same_session": True, "limit": 5, "offset": 10, "query": "amd"}
        assert result["items"][0]["review_id"] == "review-1"
        assert result["total"] == 1
        assert result["has_more"] is False
    finally:
        session.close()
