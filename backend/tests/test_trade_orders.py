from pathlib import Path
import sys

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
        }
        first = create_trade_order(session, payload)
        second = create_trade_order(session, payload)
        assert first.order is second.order
        assert second.created is False
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
    monkeypatch.setattr(trade_routes, "ingest_execution_events", _fake_ingest, raising=False)
    monkeypatch.setattr(trade_routes, "settings", type("S", (), {"data_root": str(tmp_path)}), raising=False)

    trade_routes.list_trade_orders(limit=20, offset=0)
    assert calls["called"] is True
    assert calls["path"] == str(events_path)
    session.close()
