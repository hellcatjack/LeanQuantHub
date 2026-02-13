from pathlib import Path
import sys
from datetime import datetime, timezone

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.routes import trade as trade_routes
from app.services.trade_orders import create_trade_order


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def test_client_order_id_idempotent_without_commit():
    session = _make_session()
    try:
        payload = {
            "client_order_id": "run-1-SPY",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 10,
            "order_type": "MKT",
            "params": {"client_order_id_auto": True},
        }
        first = create_trade_order(session, payload)
        second = create_trade_order(session, payload)
        assert first.order is second.order
        assert second.created is False
    finally:
        session.close()


def test_create_trade_order_clears_limit_price_for_adaptive_lmt():
    session = _make_session()
    try:
        payload = {
            "client_order_id": "run-1-adaptive",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
            "order_type": "ADAPTIVE_LMT",
            "limit_price": 100.25,
            "params": {"client_order_id_auto": True},
        }
        result = create_trade_order(session, payload)
        session.flush()
        assert result.order.order_type == "ADAPTIVE_LMT"
        assert result.order.limit_price is None
    finally:
        session.close()


def test_create_trade_order_rounds_limit_price_to_ib_tick_for_normal_price():
    session = _make_session()
    try:
        payload = {
            "client_order_id": "run-1-lmt-round-normal",
            "symbol": "AMSC",
            "side": "SELL",
            "quantity": 3,
            "order_type": "LMT",
            "limit_price": 31.6001,
            "params": {"client_order_id_auto": True},
        }
        result = create_trade_order(session, payload)
        session.flush()
        assert abs(float(result.order.limit_price or 0.0) - 31.60) < 1e-9
    finally:
        session.close()


def test_create_trade_order_rounds_limit_price_to_ib_tick_for_sub_dollar_price():
    session = _make_session()
    try:
        payload = {
            "client_order_id": "run-1-lmt-round-sub-dollar",
            "symbol": "SIRI",
            "side": "BUY",
            "quantity": 10,
            "order_type": "LMT",
            "limit_price": 0.123456,
            "params": {"client_order_id_auto": True},
        }
        result = create_trade_order(session, payload)
        session.flush()
        assert abs(float(result.order.limit_price or 0.0) - 0.1235) < 1e-9
    finally:
        session.close()


def test_create_trade_order_client_order_id_idempotent_after_limit_price_rounding():
    session = _make_session()
    try:
        base_payload = {
            "client_order_id": "run-1-lmt-round-idempotent",
            "symbol": "AMSC",
            "side": "SELL",
            "quantity": 5,
            "order_type": "LMT",
            "params": {"client_order_id_auto": True},
        }
        first = create_trade_order(session, {**base_payload, "limit_price": 31.6001})
        second = create_trade_order(session, {**base_payload, "limit_price": 31.60})
        assert second.created is False
        assert first.order is second.order
    finally:
        session.close()


def test_orders_trigger_ingest(monkeypatch, tmp_path):
    session = _make_session()

    @contextmanager
    def _get_session():
        try:
            yield session
        finally:
            pass

    calls = {"called": False, "path": None}

    def _fake_ingest(path: str) -> None:
        calls["called"] = True
        calls["path"] = path

    events_dir = tmp_path / "lean_bridge"
    events_dir.mkdir(parents=True, exist_ok=True)
    events_path = events_dir / "execution_events.jsonl"
    events_path.write_text('{"tag": "oi_1", "status": "Submitted"}\n', encoding="utf-8")

    monkeypatch.setattr(trade_routes, "get_session", _get_session)
    monkeypatch.setattr(trade_routes, "resolve_bridge_root", lambda: events_dir, raising=False)
    monkeypatch.setattr(trade_routes, "ingest_execution_events", _fake_ingest, raising=False)
    trade_routes._clear_trade_orders_response_cache()

    trade_routes.list_trade_orders(limit=20, offset=0)
    assert calls["called"] is False
    assert calls["path"] is None
    trade_routes._clear_trade_orders_response_cache()
    session.close()


def test_get_order_ingest_direct_execution_events(monkeypatch, tmp_path):
    session = _make_session()
    try:
        result = create_trade_order(
            session,
            {
                "client_order_id": "oi_0_0_123",
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 1,
                "order_type": "LMT",
                "limit_price": 100.0,
                "params": {"source": "manual"},
            },
        )
        session.commit()
        order = result.order

        @contextmanager
        def _get_session():
            try:
                yield session
            finally:
                pass

        bridge_root = tmp_path / "lean_bridge"
        direct_dir = bridge_root / f"direct_{order.id}"
        direct_dir.mkdir(parents=True, exist_ok=True)
        (direct_dir / "execution_events.jsonl").write_text(
            "\n".join(
                [
                    f'{{"order_id":1,"symbol":"AAPL","status":"Submitted","filled":0,"fill_price":0,"direction":"Buy","time":"2026-02-07T00:00:00Z","tag":"direct:{order.id}"}}',
                    f'{{"order_id":1,"symbol":"AAPL","status":"Canceled","filled":0,"fill_price":0,"direction":"Buy","time":"2026-02-07T00:01:00Z","tag":"direct:{order.id}"}}',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(trade_routes, "get_session", _get_session)
        monkeypatch.setattr(trade_routes, "resolve_bridge_root", lambda: bridge_root, raising=False)
        trade_routes._clear_trade_orders_response_cache()

        out = trade_routes.get_trade_order(order.id)
        assert out.id == order.id
        assert out.status == "CANCELED"

        refreshed = session.get(type(order), order.id)
        assert refreshed is not None
        assert refreshed.status == "CANCELED"
        assert refreshed.params
        assert refreshed.params.get("event_tag") == f"direct:{order.id}"
        trade_routes._clear_trade_orders_response_cache()
    finally:
        session.close()


def test_is_open_orders_payload_fresh_recent_snapshot():
    now = datetime(2026, 2, 11, 20, 0, 0, tzinfo=timezone.utc)
    payload = {
        "stale": False,
        "refreshed_at": "2026-02-11T19:59:30Z",
    }
    assert trade_routes._is_open_orders_payload_fresh(payload, now=now, max_age_seconds=90) is True


def test_is_open_orders_payload_fresh_old_snapshot():
    now = datetime(2026, 2, 11, 20, 0, 0, tzinfo=timezone.utc)
    payload = {
        "stale": False,
        "refreshed_at": "2026-02-11T19:57:30Z",
    }
    assert trade_routes._is_open_orders_payload_fresh(payload, now=now, max_age_seconds=90) is False


def test_is_open_orders_payload_fresh_respects_stale_flag():
    now = datetime(2026, 2, 11, 20, 0, 0, tzinfo=timezone.utc)
    payload = {
        "stale": True,
        "refreshed_at": "2026-02-11T19:59:50Z",
    }
    assert trade_routes._is_open_orders_payload_fresh(payload, now=now, max_age_seconds=90) is False
