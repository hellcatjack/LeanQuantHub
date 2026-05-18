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
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_covered_call_review_route_rejects_live_mode(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, 'get_session', _get_session)
        payload = trade_routes.CoveredCallReviewRequest(mode='live', symbol='AAPL', dry_run=True)
        with pytest.raises(Exception) as exc_info:
            trade_routes.build_covered_call_review_route(payload)
        assert getattr(exc_info.value, 'status_code', None) == 400
        assert 'paper_only' in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_review_route_rejects_non_dry_run(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, 'get_session', _get_session)
        payload = trade_routes.CoveredCallReviewRequest(mode='paper', symbol='AAPL', dry_run=False)
        with pytest.raises(Exception) as exc_info:
            trade_routes.build_covered_call_review_route(payload)
        assert getattr(exc_info.value, 'status_code', None) == 400
        assert 'dry_run_only' in str(exc_info.value)
    finally:
        session.close()


def test_covered_call_review_route_returns_service_payload(monkeypatch):
    session = _make_session()
    try:
        @contextmanager
        def _get_session():
            yield session

        monkeypatch.setattr(trade_routes, 'get_session', _get_session)
        called = {}

        def _fake_review(session_obj, payload):
            called['same_session'] = session_obj is session
            called['symbol'] = payload.symbol
            return {
                'mode': 'paper',
                'status': 'ready',
                'gate_reason': None,
                'review_id': 'review-1',
                'approval_token': 'token-1',
                'approval_expires_at': '2026-04-07T21:30:00Z',
                'eligible': {'symbol': 'AAPL'},
                'order_plan': {'underlying_symbol': 'AAPL', 'sec_type': 'OPT'},
                'runtime_summary': {'state': 'healthy'},
                'position_summary': {'shares': 200},
                'open_orders_summary': {'symbol_conflict': False},
                'artifacts': {'summary': '/tmp/summary.json', 'bundle': '/tmp/bundle.json'},
            }

        monkeypatch.setattr(trade_routes, 'build_covered_call_review', _fake_review)
        payload = trade_routes.CoveredCallReviewRequest(mode='paper', symbol='AAPL', dry_run=True)
        result = trade_routes.build_covered_call_review_route(payload)
        assert called == {'same_session': True, 'symbol': 'AAPL'}
        assert result['status'] == 'ready'
        assert result['approval_token'] == 'token-1'
    finally:
        session.close()
